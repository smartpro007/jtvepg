import requests
import json
import datetime
from datetime import timezone, timedelta
import os
import gzip
import shutil
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

# भारताची वेळ (IST = UTC + 5:30) सेट करणे (गो-लँगच्या लॉजिकप्रमाणे अचूक वेळेसाठी)
IST = timezone(timedelta(hours=5, minutes=30))

prevEpgDayCount = 1   # मागील १ दिवस
nextEpgDayCount = 2   # पुढील २ दिवस (वर्तमान दिवसासह)

# तुझी होस्टिंगची EPG API युआरएल (तशीच ठेवली आहे)
HOSTING_EPG_URL = "https://iptvmax.site/api/epg/epg.php"

def clean_xml_text(text):
    if not text:
        return ""
    text = str(text)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    text = (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("'", "&apos;")
                .replace('"', "&quot;"))
    return text

def getChannelsFromFile():
    if os.path.isfile("channels.json"):
        try:
            with open("channels.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                result = data.get("result", [])
                if isinstance(result, list):
                    return result
                elif isinstance(result, dict):
                    return list(result.values())
        except Exception as e:
            print("Error reading channels.json:", e)
    return []

def getEpg(channelId, offset, langId):
    try:
        reqUrl = f"{HOSTING_EPG_URL}?id={channelId}&offset={offset}&langId={langId}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        response = requests.get(reqUrl, headers=headers, timeout=10)
        if response.status_code == 200:
            apiData = json.loads(response.text or "{}")
            return apiData.get("epg", [])
        return []
    except Exception as e:
        return []

def writeEpgChannel(id, name, iconId, fp):
    if id is None or name is None:
        return
    safe_name = clean_xml_text(name)
    fp.write(f"\t<channel id=\"{id}\">\n")
    fp.write(f"\t\t<display-name>{safe_name}</display-name>\n")
    if iconId:
        fp.write(f"\t\t<icon src=\"https://jiotv.catchup.cdn.jio.com/dare_images/images/{iconId}\"></icon>\n")
    fp.write("\t</channel>\n")

def writeEpgProgram(channelId, epg, fp):
    if channelId is None or epg is None:
        return
    try:
        # गो-लँग कोडमधील लॉजिकप्रमाणे Epoch सेफली हँडल करणे (मिलिसेकंड्स असल्यास सेकंदात करणे)
        start_epoch_val = int(epg["startEpoch"])
        if start_epoch_val > 9999999999: 
            start_epoch_val = start_epoch_val // 1000
            
        end_epoch_val = int(epg["endEpoch"])
        if end_epoch_val > 9999999999:
            end_epoch_val = end_epoch_val // 1000

        # अचूक भारतीय वेळ (IST +0530) सेट करणे जेणेकरून प्रेझेंट प्रोग्राम वेळेवर दिसेल
        startTime = datetime.datetime.fromtimestamp(start_epoch_val, timezone.utc).astimezone(IST)
        progStart = startTime.strftime("%Y%m%d%H%M%S +0530")

        endTime = datetime.datetime.fromtimestamp(end_epoch_val, timezone.utc).astimezone(IST)
        progEnd = endTime.strftime("%Y%m%d%H%M%S +0530")

        title = clean_xml_text(epg.get("showname", ""))
        description = clean_xml_text(epg.get("episode_desc") or epg.get("description", ""))

        director = clean_xml_text(epg.get("director", ""))
        actors = [clean_xml_text(a) for a in str(epg.get("starCast", "")).split(", ")]
        category = clean_xml_text(epg.get("showCategory", ""))
        episodeNum = clean_xml_text(epg.get("episode_num", ""))

        fp.write(f"\t<programme start=\"{progStart}\" stop=\"{progEnd}\" channel=\"{channelId}\">\n")
        fp.write(f"\t\t<title lang=\"en\">{title}</title>\n")
        fp.write(f"\t\t<desc lang=\"en\">{description}</desc>\n")
        if director or any(actors):
            fp.write("\t\t<credits>\n")
            if director:
                fp.write(f"\t\t\t<director>{director}</director>\n")
            if actors:
                for actor in actors:
                    if actor.strip():
                        fp.write(f"\t\t\t<actor>{actor.strip()}</actor>\n")
            fp.write("\t\t</credits>\n")
        if category:
            fp.write(f"\t\t<category lang=\"en\">{category}</category>\n")
        if episodeNum:
            fp.write(f"\t\t<episode-num system=\"onscreen\">{episodeNum}</episode-num>\n")
        
        poster = epg.get("episodePoster", "")
        if poster:
            fp.write(f"\t\t<icon src=\"https://jiotv.catchup.cdn.jio.com/dare_images/shows/{poster}\"></icon>\n")
        fp.write("\t</programme>\n")
    except Exception as e:
        pass

def grabEpgAllChannel(day, channelList):
    print(f"Getting EPG concurrently for all channels for day {day} (IST with Safe List)")
    
    def fetch_channel(channel):
        cId = channel.get("channel_id")
        if cId:
            epgData = getEpg(cId, day, 6)
            return cId, epgData
        return None, []

    all_programs = []
    # मल्टिथ्रेडिंग वापरून सुरक्षितपणे डेटा लिस्टमध्ये गोळा करणे (फाईल कोरी होण्यास प्रतिबंध)
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(fetch_channel, channel): channel for channel in channelList}
        for future in as_completed(futures):
            try:
                cId, epgData = future.result()
                if epgData and cId:
                    for epg in epgData:
                        all_programs.append((cId, epg))
            except Exception as e:
                pass

    with open(f"program{day}.xml", "w", encoding='utf-8') as programFile:
        for cId, epg in all_programs:
            writeEpgProgram(cId, epg, programFile)

def mergeEpgData(channelList):
    with open("channels.xml", "w", encoding='utf-8') as channelFile:
        for channel in channelList:
            writeEpgChannel(channel.get("channel_id"), channel.get("channel_name"), channel.get("logoUrl"), channelFile)

    with open("channels.xml", "r", encoding='utf-8') as channelsFile:
        channelsContent = channelsFile.read()

    with open("epg.xml", "w", encoding='utf-8') as epgFile:
        epgFile.write("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
        epgFile.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n")
        epgFile.write("<tv generator-info-name=\"JioTV EPG\" generator-info-url=\"https://github.com\">\n")
        epgFile.write(channelsContent)
        for day in range((prevEpgDayCount * -1), nextEpgDayCount):
            if os.path.isfile(f'./program{day}.xml'):
                with open(f'./program{day}.xml', "r", encoding='utf-8') as programsFile:
                    epgFile.write(programsFile.read())
        epgFile.write("</tv>\n")

    with open("epg1d.xml", "w", encoding='utf-8') as epgFile1d:
        epgFile1d.write("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
        epgFile1d.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n")
        epgFile1d.write("<tv generator-info-name=\"JioTV EPG\" generator-info-url=\"https://github.com\">\n")
        epgFile1d.write(channelsContent)
        if os.path.isfile('./program0.xml'):
            with open('./program0.xml', "r", encoding='utf-8') as programsFile:
                epgFile1d.write(programsFile.read())
        epgFile1d.write("</tv>\n")

# Process starts here
channelList = getChannelsFromFile()
if not channelList:
    print("channels.json not found or empty! Exiting.")
    exit(1)

print(f"Total channels loaded from JSON: {len(channelList)}")

for day in range((prevEpgDayCount * -1), nextEpgDayCount):
    grabEpgAllChannel(day, channelList)

mergeEpgData(channelList)

with open('epg.xml', 'rb') as f_in:
    with gzip.open('epg.xml.gz', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)

for day in range((prevEpgDayCount * -1), nextEpgDayCount):
    if os.path.isfile(f'./program{day}.xml'):
        os.remove(f'./program{day}.xml')

if os.path.isfile('./channels.xml'):
    os.remove('./channels.xml')

print("epg.xml.gz and epg1d.xml successfully created with Go logic & Safe Multithreading!")
