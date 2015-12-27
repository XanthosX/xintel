###########################################################################
#  Vintel - Visual Intel Chat Analyzer                                    #
#  Copyright (C) 2014-15 Sebastian Meyer (sparrow.242.de+eve@gmail.com )  #
#                                                                         #
#  This program is free software: you can redistribute it and/or modify   #
#  it under the terms of the GNU General Public License as published by   #
#  the Free Software Foundation, either version 3 of the License, or      #
#  (at your option) any later version.                                    #
#                                                                         #
#  This program is distributed in the hope that it will be useful,        #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of         #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          #
#  GNU General Public License for more details.                           #
#                                                                         #
#                                                                         #
#  You should have received a copy of the GNU General Public License      #
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.  #
###########################################################################

import datetime
import os
import time
from collections import namedtuple

from bs4 import BeautifulSoup
from bs4.element import NavigableString

from parser_functions import parseUrls, parseShips, parseSystems
from parser_functions import parseStatus

from PyQt4 import QtGui

from vi import states

# Names the local chatlogs could start with (depends on l10n of the client)
LOCAL_NAMES = ("Lokal", "Local")

class ChatParser(object):
    """ ChatParser will analyze every new line that was found inside the Chatlogs.
    """
    
    def __init__(self, path, rooms, systems):
        """ path = the path with the logs
            rooms = the rooms to parse"""
        self.path = path  # the path with the chatlog
        self.rooms = rooms  # the rooms to watch (excl. local)
        self.systems = systems  # the known systems as dict name: system
        self.fileData = {}  # informations about the files in the directory
        self.knownMessages = []  # message we allready analyzed
        self.locations = {}  # informations about the location of a char
        self.ignoredPaths = []
        self._collectInitFileData(path)
        
    
    def _collectInitFileData(self, path):
        currentTime = time.time()
        maxDiff = 60*60*24  # what is 1 day in seconds
        for fileName in os.listdir(path):
            fullPath = os.path.join(path, fileName)
            fileTime = os.path.getmtime(fullPath)
            if currentTime - fileTime < maxDiff:
                self.addFile(fullPath)
    
    
    def addFile(self, path):
        lines = None
        content = ""
        filename = os.path.basename(path)
        roomName = filename[:-20]
        with open(path, "r") as f:
            content = f.read()
        try:
            content = content.decode("utf-16-le")
        except Exception as e:
            self.ignoredPaths.append(path)
            QtGui.QMessageBox.warning(None, "Read a log file failed!", "File: {0} - problem: {1}".format(path, str(e)), "OK")
            return None
            
        lines = content.split("\n")
        if (path not in self.fileData or (roomName in LOCAL_NAMES and "charname" not in self.fileData.get(path, []))):
            self.fileData[path] = {}
            if roomName in LOCAL_NAMES:
                charName = None
                sessionStart = None  
                # for local-chats we need more infos
                for line in lines:
                    if "Listener:" in line:
                        charName = line[line.find(":")+1:].strip()
                    elif "Session started:" in line:
                        sessionstr = line[line.find(":")+1:].strip()
                        sessionStart = datetime.datetime.strptime(sessionstr, "%Y.%m.%d %H:%M:%S")
                    if charName and sessionStart:
                        self.fileData[path]["charname"] = charName
                        self.fileData[path]["sessionstart"] = sessionStart
                        break
        self.fileData[path]["lines"] = len(lines)
        return lines
    
    
    def _lineToMessage(self, line, roomName):
        # finding the timestamp
        timeStart = line.find("[") + 1
        timeEnds = line.find("]")
        timeStr = line[timeStart:timeEnds].strip()
        try:
            timestamp = datetime.datetime.strptime(timeStr, "%Y.%m.%d %H:%M:%S")
        except ValueError:
            return None
        # finding the username of the poster
        userends = line.find(">")
        username = line[timeEnds+1:userends].strip()
        # finding the pure message
        text = line[userends+1:].strip()  # text will the text to work an
        originalText = text
        formatedText = u"<rtext>{0}</rtext>".format(text)
        soup = BeautifulSoup(formatedText)
        rtext = soup.select("rtext")[0]
        systems = set()
        utext = text.upper()
        
        # KOS request
        if roomName.startswith("=VI="):
            return Message(roomName, "xxx " + text, timestamp, username, systems, "XXX " + utext, status=states.KOS_STATUS_REQUEST)
        elif utext.startswith("XXX "):
            return Message(roomName, text, timestamp, username, systems, utext, status=states.KOS_STATUS_REQUEST)
        elif utext.startswith("VINTELSOUND_TEST"):
            return Message(roomName, text, timestamp, username, systems, utext, status=states.SOUND_TEST)
        if roomName not in self.rooms:
            return None
            
        # and now creating message object
        message = Message(roomName, "", timestamp, username, systems, text, originalText)
        # is the message allready here? may happen if someone plays > 1 account
        if message in self.knownMessages:
            message.status = states.IGNORE
            return message    
        # and going on with parsing
        removeChars = ("*", "?", ",", "!")
        for char in removeChars:
            text = text.replace(char, "")
        # ships in the message?
        run = True
        while run:
            run = parseShips(rtext)
        # urls in the message?
        run = True
        while run:
            run = parseUrls(rtext)
        # trying to find the system in the text
        run = True
        while run:
            run = parseSystems(self.systems, rtext, systems)
        # and the status
        parsedStatus = parseStatus(rtext)
        status = parsedStatus if parsedStatus is not None else states.ALARM
        # if message says clear and no system? Maybe an answer to a request?
        if status == states.CLEAR and not systems:
            maxSearch = 2  # we search only max_search messages in the room
            for count, oldMessage in enumerate(oldMessage for oldMessage in self.knownMessages[-1::-1] if oldMessage.room==roomName):
                if oldMessage.systems and oldMessage.status == states.REQUEST:
                    for system in oldMessage.systems:
                        systems.add(system)
                    break
                if count > maxSearch:
                    break
        message.message = unicode(rtext)
        message.status = status
        self.knownMessages.append(message)
        if systems:
           for system in systems:
              system.messages.append(message)
        return message 


    def _parseLocal(self, path, line):
        message = []
        """ Parsing a line from the local chat. Can contain the system of the char
        """
        charName = self.fileData[path]["charname"]
        if charName not in self.locations:
            self.locations[charName] = {"system": "?", "timestamp": datetime.datetime(1970, 1, 1, 0, 0, 0, 0)}
        # finding the timestamp
        timeStart = line.find("[") + 1
        timeEnds = line.find("]")
        timeStr = line[timeStart:timeEnds].strip()
        timestamp = datetime.datetime.strptime(timeStr, "%Y.%m.%d %H:%M:%S")
        # finding the username of the poster
        userends = line.find(">")
        username = line[timeEnds+1:userends].strip()
        # finding the pure message
        text = line[userends+1:].strip()  # text will the text to work an
        if username in ("EVE-System", "EVE System"):
            if ":" in text:
                system = text.split(":")[1].strip().replace("*", "").upper()
            else:
                system = "?"
            if timestamp > self.locations[charName]["timestamp"]:
                self.locations[charName]["system"] = system
                self.locations[charName]["timestamp"] = timestamp
                message = Message("", "", timestamp, charName, [system,], "", status=states.LOCATION)
        return message
    
    
    def fileModified(self, path):
        messages = []
        if path in self.ignoredPaths:
            return []
        # checking if we must do anything with the changed file.
        # we are only need those, which name is in the rooms-list
        # EvE names the file like room_20140913_200737.txt, so we don't need
        # the last 20 chars
        filename = os.path.basename(path)
        roomName = filename[:-20]
        if path not in self.fileData:
            # seems eve created a new file. New Files have 12 lines header
            self.fileData[path] = {"lines": 13}
        oldLength = self.fileData[path]["lines"]
        lines = self.addFile(path)
        if path in self.ignoredPaths:
            return []
        for line in lines[oldLength - 1:]:
            line = line.strip()
            if len(line) > 2:
                message = None
                if roomName in LOCAL_NAMES:
                    message = self._parseLocal(path, line)
                else:
                    message = self._lineToMessage(line, roomName)
                if message:
                    messages.append(message)
        return messages



class Message(object):
   
    def __init__(self, room, message, timestamp, user, systems, utext, plainText="", status=states.ALARM):
        self.room = room             # chatroom the message was posted
        self.message = message       # the messages text
        self.timestamp = timestamp   # time stamp of the massage
        self.user = user             # user who posted the message
        self.systems = systems       # list of systems mentioned in the message
        self.status = status         # status related to the message
        self.utext = utext           # the text in UPPER CASE
        self.plainText = plainText   # plain text of the message, as posted
        # if you add the message to a widget, please add it to widgets
        self.widgets = []

    def __key(self):
        return(self.room, self.plainText, self.timestamp, self.user)

    def __eq__(x, y):
        return x.__key() == y.__key()

    def __hash__(self):
        return hash(self.__key())