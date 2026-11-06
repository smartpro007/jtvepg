import requests
import json
import datetime
from datetime import timezone, timedelta
import os
import gzip
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# भारताची वेळ (IST = UTC + 5:30) सेट करणे
IST = timezone(timedelta(hours=5, minutes=30))

# ----------------- जिओटीव्ही सेटिंग्ज -----------------
JIOTV_CHANNELS_URL = "https://raw.githubusercontent.com/smartpro007/jtvepg/refs/heads/main/channels.json"
JIOTV_EPG_URL = "https://iptvmax.site/api/epg/epg.php"
prevEpgDayCount = 1   
nextEpgDayCount = 2   

# ----------------- कॉमन फंक्शन्स -----------------
def clean_xml_text(text):
    if not text:
        return ""
    text = str(text)
    text = re.sub(r'\s*-\d+\s*$', '', text)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    text = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("'", "&apos;")
                .replace('"', "&quot;"))
    return text

def extract_channels_and_programmes(xml_content):
    channels = ""
    programmes = ""
    ch_start = xml_content.find('<channel')
    prog_start = xml_content.find('<programme')
    
    if prog_start != -1:
        channels = xml_content[ch_start:prog_start]
        programmes = xml_content[prog_start:xml_content.rfind('</tv>')]
    else:
        channels = xml_content
    return channels, programmes

# ----------------- स्टेप १: टाटा प्ले EPG जनरेट करणे -----------------
def generate_tataplay_data():
    print("\n--- [Step 1/2] Fetching Tata Play EPG ---")
    
    today = datetime.datetime.now(IST)
    dates_to_fetch = [
        (today - timedelta(days=1)).strftime('%d-%m-%Y'),
        today.strftime('%d-%m-%Y'),
        (today + timedelta(days=1)).strftime('%d-%m-%Y')
    ]

    all_channels_dict = {}
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin': 'https://watch.tataplay.com',
        'Referer': 'https://watch.tataplay.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'content-type': 'application/json',
        'locale': 'ENG',
        'me': 'web'
    }

    for dateStr in dates_to_fetch:
        print(f"Processing Tata Play Date: {dateStr}")
        offset = 0
        limit = 20
        total = 836
        request_count = 0

        while offset < total:
            responseData = None
            retries = 3
            while retries > 0:
                try:
                    resp = requests.get(
                        f"https://tm.tapi.videoready.tv/portal-search/pub/api/v1/channels/schedule?date={dateStr}&languageFilters=&genreFilters=&limit={limit}&offset={offset}",
                        headers=headers, timeout=15
                    )
                    responseData = resp.json().get('data')
                    break
                except Exception as err:
                    retries -= 1
                    time.sleep(60)

            if not responseData or not responseData.get('channelList'):
                offset += limit
                continue

            total = responseData.get('total', total)
            for channel in responseData['channelList']:
                if channel.get('title') and channel['title'] != '.':
                    site_id = channel['id']
                    name = channel['title']
                    logo = channel.get('transparentImageUrl') or channel.get('thumbnailImage') or ''
                    items = channel.get('epg', [])

                    if site_id not in all_channels_dict:
                        all_channels_dict[site_id] = {'id': site_id, 'name': name, 'logo': logo, 'epgItems': []}

                    for item in items:
                        all_channels_dict[site_id]['epgItems'].append(item)

            offset += limit
            request_count += 1
            if request_count % 5 == 0:
                time.sleep(45)
            else:
                time.sleep(2)

    # टाटा प्ले XML स्ट्रक्चर बनवणे
    tp_xml = ""
    for ch in all_channels_dict.values():
        tp_xml += f'  <channel id="{ch["id"]}">\n'
        tp_xml += f'    <display-name>{clean_xml_text(ch["name"])}</display-name>\n'
        if ch['logo']:
            tp_xml += f'    <icon src="{clean_xml_text(ch["logo"])}" />\n'
        tp_xml += f'  </channel>\n'

    for ch in all_channels_dict.values():
        for item in ch['epgItems']:
            try:
                start_time = datetime.datetime.fromtimestamp(int(item['startTime']) / 1000, IST).strftime('%Y%m%d%H%M%S +0530')
                end_time = datetime.datetime.fromtimestamp(int(item['endTime']) / 1000, IST).strftime('%Y%m%d%H%M%S +0530')
                tp_xml += f'  <programme start="{start_time}" stop="{end_time}" channel="{ch["id"]}">\n'
                tp_xml += f'    <title lang="en">{clean_xml_text(item.get("title", ""))}</title>\n'
                if item.get('desc'):
                    tp_xml += f'    <desc lang="en">{clean_xml_text(item["desc"])}</desc>\n'
                if item.get('boxCoverImage'):
                    tp_xml += f'    <icon src="{clean_xml_text(item["boxCoverImage"])}" />\n'
                tp_xml += f'  </programme>\n'
            except:
                pass

    print("Tata Play EPG fetched successfully.")
    return tp_xml

# ----------------- स्टेप २: जिओटीव्ही EPG जनरेट करणे -----------------
def generate_jiotv_data():
    print("\n--- [Step 2/2] Fetching JioTV EPG ---")
    try:
        resp = requests.get(JIOTV_CHANNELS_URL, timeout=15)
        data = resp.json()
        channelList = data.get("result", [])
        if isinstance(channelList, dict):
            channelList = list(channelList.values())
    except Exception as e:
        print("Error loading JioTV channels:", e)
        return ""

    print(f"Total JioTV channels loaded: {len(channelList)}")

    def get_jio_epg(cId, offset):
        try:
            r = requests.get(f"{JIOTV_EPG_URL}?id={cId}&offset={offset}&langId=6", headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if r.status_code == 200:
                return r.json().get("epg", [])
        except:
            pass
        return []

    jio_xml = ""
    # चॅनेल्स जोडणे
    for channel in channelList:
        cId = channel.get("channel_id")
        cName = channel.get("channel_name")
        logo = channel.get("logoUrl")
        if cId and cName:
            jio_xml += f'  <channel id="{cId}">\n'
            jio_xml += f'    <display-name>{clean_xml_text(cName)}</display-name>\n'
            if logo:
                jio_xml += f'    <icon src="https://jiotv.catchup.cdn.jio.com/dare_images/images/{logo}" />\n'
            jio_xml += f'  </channel>\n'

    # प्रोग्राम्स जोडणे
    for day in range((prevEpgDayCount * -1), nextEpgDayCount):
        print(f"Fetching JioTV EPG for day offset: {day}")
        def fetch_prog(ch):
            cId = ch.get("channel_id")
            if cId:
                epgs = get_jio_epg(cId, day)
                return cId, epgs
            return None, []

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(fetch_prog, ch) for ch in channelList]
            for future in as_completed(futures):
                cId, epgs = future.result()
                if cId and epgs:
                    for epg in epgs:
                        try:
                            start_ep = int(epg["startEpoch"])
                            if start_ep > 9999999999: start_ep //= 1000
                            end_ep = int(epg["endEpoch"])
                            if end_ep > 9999999999: end_ep //= 1000

                            start_time = datetime.datetime.fromtimestamp(start_ep, timezone.utc).astimezone(IST).strftime('%Y%m%d%H%M%S +0530')
                            end_time = datetime.datetime.fromtimestamp(end_ep, timezone.utc).astimezone(IST).strftime('%Y%m%d%H%M%S +0530')

                            title = clean_xml_text(epg.get("showname", ""))
                            desc = clean_xml_text(epg.get("episode_desc") or epg.get("description", ""))

                            jio_xml += f'  <programme start="{start_time}" stop="{end_time}" channel="{cId}">\n'
                            jio_xml += f'    <title lang="en">{title}</title>\n'
                            if desc:
                                jio_xml += f'    <desc lang="en">{desc}</desc>\n'
                            jio_xml += f'  </programme>\n'
                        except:
                            pass

    print("JioTV EPG fetched successfully.")
    return jio_xml

# ----------------- मुख्य प्रक्रिया (Main Execution) -----------------
def main():
    print("Starting Combined Tata Play & JioTV EPG Generator...")

    tp_xml_content = generate_tataplay_data()
    jio_xml_content = generate_jiotv_data()

    tp_ch, tp_prog = extract_channels_and_programmes(tp_xml_content)
    jio_ch, jio_prog = extract_channels_and_programmes(jio_xml_content)

    final_channels = tp_ch + jio_ch
    final_programmes = tp_prog + jio_prog

    output_xml = 'final_merged_epg.xml'
    output_gz = 'final_merged_epg.xml.gz'

    print("\nAssembling final merged XML file...")
    with open(output_xml, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<tv generator-info-name="Combined-TataPlay-JioTV-EPG">\n')
        f.write(final_channels)
        f.write(final_programmes)
        f.write('</tv>\n')

    print(f"Compressing to {output_gz}...")
    with open(output_xml, 'rb') as f_in:
        with gzip.open(output_gz, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    if os.path.exists(output_xml):
        os.remove(output_xml)

    print("==================================================")
    print(f"SUCCESS! Final EPG generated: {output_gz}")
    print("==================================================")

if __name__ == '__main__':
    main()
    
