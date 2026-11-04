import requests
import json
import datetime
import os
import gzip
import shutil

prevEpgDayCount = 7
nextEpgDayCount = 2

# JioTV च्या चॅनेलची फिक्स यादी (तुला हवी असलेली इतर चॅनेल्स यात ऍड करू शकतोस)
channelList = [
    {"channel_id": 144, "channel_name": "Colors HD", "logoUrl": "Colors_HD.png"},
    {"channel_id": 137, "channel_name": "Star Plus HD", "logoUrl": "Star_Plus_HD.png"},
    {"channel_id": 149, "channel_name": "Zee TV HD", "logoUrl": "Zee_TV_HD.png"},
    # येथे तुला हवी ती इतर चॅनेल्स "channel_id" आणि "channel_name" सोबत टाकू शकतोस
]


def getEpg(channelId, offset, langId):
    try:
        reqUrl = f"https://jiotv.data.cdn.jio.com/apis/v1.3/getepg/get?channel_id={channelId}&offset={offset}&langId={langId}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36"
        }
        response = requests.get(reqUrl, headers=headers)
        print("Channel ID " + str(channelId) + " EPG status: " + str(response.status_code))
        if (response.status_code == 200):
            apiData = json.loads(response.text or "{}")
            return apiData.get("epg", [])
        return []
    except Exception as e:
        print(f"Error fetching EPG for {channelId}: {e}")
        return []


def writeEpgChannel(id, name, iconId, fp):
    if id is None or name is None:
        return

    name = name.replace("&", "&amp;")
    name = name.replace("<", "&lt;")
    name = name.replace(">", "&gt;")
    name = name.replace("'", "&apos;")
    name = name.replace('"', "&quot;")
    fp.write("\t<channel id=\""+str(id)+"\">\n")
    fp.write("\t\t<display-name>"+str(name)+"</display-name>\n")
    fp.write("\t\t<icon src=\"https://jiotv.catchup.cdn.jio.com/dare_images/images/" +
             str(iconId)+"\"></icon>\n")
    fp.write("\t</channel>\n")


def writeEpgProgram(channelId, epg, fp):
    if channelId is None or epg is None:
        return
    try:
        startTime = datetime.datetime.fromtimestamp(int(epg["startEpoch"]/1000))
        progStart = startTime.strftime("%Y%m%d%H%M%S +0000")

        endTime = datetime.datetime.fromtimestamp(int(epg["endEpoch"]/1000))
        progEnd = endTime.strftime("%Y%m%d%H%M%S +0000")

        title = str(epg.get("showname", ""))
        title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")

        description = str(epg.get("episode_desc") or epg.get("description", ""))
        description = description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&apos;").replace('"', "&quot;")

        director = epg.get("director", "")
        actors = str(epg.get("starCast", "")).split(", ")
        category = epg.get("showCategory", "")
        episodeNum = epg.get("episode_num", "")

        fp.write("\t<programme start=\""+str(progStart)+"\" stop=\"" +
                 str(progEnd)+"\" channel=\""+str(channelId) + "\">\n")
        fp.write("\t\t<title lang=\"en\">" + title + "</title>\n")
        fp.write("\t\t<desc lang=\"en\">" + description + "</desc>\n")
        if(director or len(actors)):
            fp.write("\t\t<credits>\n")
            if(director):
                fp.write("\t\t\t<director>" + str(director) + "</director>\n")
            if(len(actors)):
                for actor in actors:
                    if actor.strip():
                        fp.write("\t\t\t<actor>" + actor.strip() + "</actor>\n")
            fp.write("\t\t</credits>\n")
        if(category):
            fp.write("\t\t<category lang=\"en\">" + str(category) + "</category>\n")
        if(episodeNum):
            fp.write("\t\t<episode-num system=\"onscreen\">" + str(episodeNum) + "</episode-num>\n")
        
        poster = epg.get("episodePoster", "")
        if poster:
            fp.write("\t\t<icon src=\"https://jiotv.catchup.cdn.jio.com/dare_images/shows/" + str(poster) + "\"></icon>\n")
        fp.write("\t</programme>\n")
    except Exception as e:
        print("Error writing program:", e)


def grabEpgAllChannel(day):
    print(f"\n\nGetting EPG for all channels for day {day}\n")
    programFile = open(f"program{day}.xml", "a", encoding='utf-8')
    progress = 0
    for channel in channelList:
        print(f"Getting EPG for {channel['channel_id']} {channel['channel_name']} day {day}")
        epgData = getEpg(channel["channel_id"], day, 6)
        for epg in epgData:
            writeEpgProgram(channel["channel_id"], epg, programFile)
        progress += 1
        print(f"progress {progress}/{len(channelList)}")
    programFile.close()


def rotateEpg():
    for day in range((prevEpgDayCount * -1), nextEpgDayCount):
        if (os.path.isfile(f'./program{day}.xml')
            and os.path.isfile(f'./program{day+1}.xml')
                and (day != (nextEpgDayCount - 1))):
            with open(f'./program{day}.xml', "w", encoding='utf-8') as preProgFile:
                with open(f'./program{day+1}.xml', "r", encoding='utf-8') as nextProgFile:
                    preProgFile.write(nextProgFile.read())
    if (os.path.isfile(f'./program{nextEpgDayCount-1}.xml')):
        os.remove(f'./program{nextEpgDayCount-1}.xml')


def mergeEpgData():
    with open("channels.xml", "r", encoding='utf-8') as channelsFile:
        channelsContent = channelsFile.read()

    with open("epg.xml", "w", encoding='utf-8') as epgFile:
        epgFile.write("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
        epgFile.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n")
        epgFile.write("<tv generator-info-name=\"JioTV EPG\" generator-info-url=\"https://github.com\">\n")
        epgFile.write(channelsContent)
        for day in range((prevEpgDayCount * -1), nextEpgDayCount):
            if (os.path.isfile(f'./program{day}.xml')):
                with open(f'./program{day}.xml', "r", encoding='utf-8') as programsFile:
                    epgFile.write(programsFile.read())
        epgFile.write("</tv>\n")

    # Single day epg
    with open("channels.xml", "r", encoding='utf-8') as channelsFile:
        channelsContent = channelsFile.read()

    with open("epg1d.xml", "w", encoding='utf-8') as epgFile1d:
        epgFile1d.write("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n")
        epgFile1d.write("<!DOCTYPE tv SYSTEM \"xmltv.dtd\">\n")
        epgFile1d.write("<tv generator-info-name=\"JioTV EPG\" generator-info-url=\"https://github.com\">\n")
        epgFile1d.write(channelsContent)
        if (os.path.isfile('./program0.xml')):
            with open('./program0.xml', "r", encoding='utf-8') as programsFile:
                epgFile1d.write(programsFile.read())
        epgFile1d.write("</tv>\n")


# Process starts here
with open("channels.xml", "w", encoding='utf-8') as channelFile:
    for channel in channelList:
        writeEpgChannel(channel["channel_id"], channel["channel_name"], channel["logoUrl"], channelFile)

rotateEpg()

for day in range((prevEpgDayCount * -1), nextEpgDayCount):
    if not os.path.isfile(f'./program{day}.xml'):
        grabEpgAllChannel(day)

mergeEpgData()

# Compress to gzip
with open('epg.xml', 'rb') as f_in:
    with gzip.open('epg.xml.gz', 'wb') as f_out:
        shutil.copyfileobj(f_in, f_out)

print("epg.xml.gz created successfully!")
print("Action complete")
