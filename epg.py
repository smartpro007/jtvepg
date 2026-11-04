import requests
import json
import datetime
import os
import gzip
import shutil

prevEpgDayCount = 1   # मागील १ दिवस
nextEpgDayCount = 2   # पुढील २ दिवस (वर्तमान दिवसासह)

def getChannels():
    reqUrl = "https://jiotv.data.cdn.jio.com/apis/v1.4/getMobileChannelList/get/?os=android&devicetype=phone"
    headers = {
        "User-Agent": "okhttp/4.2.2",
        "os": "android",
        "devicetype": "phone"
    }
    try:
        response = requests.get(reqUrl, headers=headers)
        print("Channels API Status: " + str(response.status_code))
        if response.status_code == 200:
            apiData = json.loads(response.text or "{}")
            return apiData.get("result", [])
    except Exception as e:
        print("Error fetching channels:", e)
    return []


def getEpg(channelId, offset, langId):
    try:
        reqUrl = f"https://jiotv.data.cdn.jio.com/apis/v1.3/getepg/get?channel_id={channelId}&offset={offset}&langId={langId}"
        headers = {
            "User-Agent": "okhttp/4.2.2"
        }
        response = requests.get(reqUrl, headers=headers)
        if response.status_code == 200:
            apiData = json.loads(response.text or "{}")
            return apiData.get("epg", [])
        return []
    except Exception as e:
        return []


def writeEpgChannel(id, name, iconId, fp):
    if id is None or name is None:
        return
    name = str(name).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")
    fp.write(f"\t<channel id=\"{id}\">\n")
    fp.write(f"\t\t<display-name>{name}</display-name>\n")
    fp.write(f"\t\t<icon src=\"https://jiotv.catchup.cdn.jio.com/dare_images/images/{iconId}\"></icon>\n")
    fp.write("\t</channel>\n")


def writeEpgProgram(channelId, epg, fp):
    if channelId is None or epg is None:
        return
    try:
        startTime = datetime.datetime.fromtimestamp(int(epg["startEpoch"]/1000))
        progStart = startTime.strftime("%Y%m%d%H%M%S +0000")

        endTime = datetime.datetime.fromtimestamp(int(epg["endEpoch"]/1000))
        progEnd = endTime.strftime("%Y%m%d%H%M%S +0000")

        title = str(epg.get("showname", "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")
        description = str(epg.get("episode_desc") or epg.get("description", "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")

        director = epg.get("director", "")
        actors = str(epg.get("starCast", "")).split(", ")
        category = epg.get("showCategory", "")
        episodeNum = epg.get("episode_num", "")

        fp.write(f"\t<programme start=\"{progStart}\" stop=\"{progEnd}\" channel=\"{channelId}\">\n")
        fp.write(f"\t\t<title lang=\"en\">{title}</title>\n")
        fp.write(f"\t\t<desc lang=\"en\">{description}</desc>\n")
        if director or len(actors):
            fp.write("\t\t<credits>\n")
            if director:
                fp.write(f"\t\t\t<director>{director}</director>\n")
            if len(actors):
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
    print(f"Getting EPG for all channels for day {day}")
    programFile = open(f"program{day}.xml", "w", encoding='utf-8')
    for channel in channelList:
        cId = channel.get("channel_id")
        epgData = getEpg(cId, day, 6)
        if epgData:
            for epg in epgData:
                writeEpgProgram(cId, epg, programFile)
    programFile.close()


def mergeEpgData(channelList):
    # चॅनेल फाईल तयार करणे
    with open("channels.xml", "w", encoding='utf-8') as channelFile:
        for channel in channelList:
            writeEpgChannel(channel.get("channel_id"), channel.get("channel_name"), channel.get("logoUrl"), channelFile)

    with open("channels.xml", "r", encoding='utf-8') as channelsFile:
        channelsContent = channelsFile.read()

    # संपूर्ण epg.xml तयार करणे
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

    # फक्त आजचा (Single day) epg1d.xml तयार करणे
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
channelList = getChannels()
if not channelList:
    print("Could not fetch channel list. Exiting.")
    exit(1)

print(f"Total channels found: {len(channelList)}")

for day in range((prevEpgDayCount * -1), nextEpgDayCount):
    grabEpgAllChannel(day, channelList)

mergeEpgData(channelList)

# epg.xml ला थेट epg.xml.gz मध्ये कॉम्प्रेस करणे
with open('epg.xml', 'rb') as f_in:
    with gzip.open('epg.xml.gz', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)

# तात्पुरत्या program फाईल्स डिलीट करणे
for day in range((prevEpgDayCount * -1), nextEpgDayCount):
    if os.path.isfile(f'./program{day}.xml'):
        os.remove(f'./program{day}.xml')

# channels.xml आणि मुख्य epg.xml सुद्धा रिपॉझिटरीवरून काढायचे असल्यास काढू शकतो, पण हवी असल्यास ठेवू शकतो
if os.path.isfile('./epg.xml'):
    os.remove('./epg.xml')

print("epg.xml.gz and epg1d.xml created successfully for all channels!")
print("Action complete")
