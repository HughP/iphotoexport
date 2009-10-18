'''Helpers to use exiftool to read and update image meta data.
Created on May 29, 2009

@author: tsporkert@gmail.com
'''

# Copyright 2009 Tilman Sporkert
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import datetime
import os
import sys
import tempfile
import time

from xml.dom import minidom
from xml import parsers

import systemutils

_EXIFTOOL = "/usr/bin/exiftool"

def check_exif_tool():
  """Tests if a compatible version of exiftool is available."""
  try:
    output = systemutils.execandcombine((_EXIFTOOL, "-ver"))
    version = float(output)
    if version < 7.47:
      print >> sys.stderr, "You have version " + str(version) + " of exiftool."
      print >> sys.stderr, """
Please upgrade to version 7.47 or newer of exiftool. You can download a copy
from http://www.sno.phy.queensu.ca/~phil/exiftool/. iphoto_export wants to use
the new -X option to read IPTC data in XML format."""
      return False
    return True
  except StandardError:
    print >> sys.stderr, """Cannot execute "%s".

Make sure you have exiftool installed as /usr/bin/exiftool. You can download a
copy from http://www.sno.phy.queensu.ca/~phil/exiftool/.
""" % (_EXIFTOOL)
  return False


def get_iptc_data(image_file):
  """get caption, keywords, datetime, rating, and GPS info all in one 
     operation."""
  output = systemutils.execandcombine(
      (_EXIFTOOL, "-X", "-m", "-q", "-q", '-c', '%.6f', "-Keywords", 
       "-Caption-Abstract", "-DateTimeOriginal", "-Rating", "-GPSLatitude", 
       "-GPSLongitude", "%s" % (image_file.encode('utf8'))))

  keywords = []
  caption = None
  date_time_original = None
  rating = 0
  gps = None
  if output:
    try:
      gps_latitude = None
      gps_longitude = None
      xml_data = minidom.parseString(output)
  
      for xml_desc in xml_data.getElementsByTagName("rdf:Description"):
        for xml_keywords in xml_desc.getElementsByTagName("IPTC:Keywords"):
          if (xml_keywords.firstChild.nodeValue and
              xml_keywords.firstChild.nodeValue != "\n"):
            keywords.append(xml_keywords.firstChild.nodeValue)
          for xml_bag in xml_keywords.getElementsByTagName("rdf:Bag"):
            for xml_li in xml_bag.getElementsByTagName("rdf:li"):
              keywords.append(xml_li.firstChild.nodeValue)
        for xml_caption in xml_data.getElementsByTagName(
            "IPTC:Caption-Abstract"):
          caption = xml_caption.firstChild.nodeValue
        for xml_element in xml_data.getElementsByTagName(
            "ExifIFD:DateTimeOriginal"):
          date_time_original = time.strptime(xml_element.firstChild.nodeValue,
                                             "%Y:%m:%d %H:%M:%S")
          date_time_original = datetime.datetime(date_time_original.tm_year,
                                                 date_time_original.tm_mon,
                                                 date_time_original.tm_mday,
                                                 date_time_original.tm_hour,
                                                 date_time_original.tm_min,
                                                 date_time_original.tm_sec)
        for xml_rating in xml_data.getElementsByTagName("XMP-xmp:Rating"):
          rating = int(xml_rating.firstChild.nodeValue)
        for xml_element in xml_data.getElementsByTagName(
            "Composite:GPSLatitude"):
          gps_latitude = xml_element.firstChild.nodeValue
        for xml_element in xml_data.getElementsByTagName(
            "Composite:GPSLongitude"):
          gps_longitude = xml_element.firstChild.nodeValue
      xml_data.unlink()
      if gps_latitude and gps_longitude:
        latitude = float(gps_latitude[0:-2])
        if gps_latitude.endswith(" S"):
          latitude = -latitude
        longitude = float(gps_longitude[0:-2])
        if gps_longitude.endswith(" W"):
          longitude = -longitude
        gps = (latitude, longitude)
    except parsers.expat.ExpatError, ex:
      print >> sys.stderr, "Could not parse exiftool output %s: %s" % (
          output, ex)

  return (keywords, caption, date_time_original, rating, gps)


def update_iptcdata(filepath, new_caption, new_keywords, new_datetime, 
                    new_rating, new_gps): 
  """Updates the caption and keywords of an image file."""
  # Some cameras write into ImageDescription, so we wipe it out to not cause
  # conflicts with Caption-Abstract
  command = [_EXIFTOOL, '-F', '-P', '-ImageDescription=']
  tmp = None
  if not new_caption is None:
    tmpfd, tmp = tempfile.mkstemp(dir="/var/tmp")
    os.close(tmpfd)
    file1 = open(tmp, "w")
    if not new_caption:
      # you can't set caption to an empty string
      new_caption = " "
    print >> file1, new_caption.encode("utf-8")
    file1.close()
    command.append('-Caption-Abstract<=%s' % (tmp))
  
  if new_datetime:
    command.append('-DateTimeOriginal="%s"' % (
      new_datetime.strftime("%Y:%m:%d %H:%M:%S")))
  if new_keywords:
    for keyword in new_keywords:
      command.append(u'-keywords=%s' % (keyword))
  if new_rating:
    command.append('-Rating=%d' % (new_rating))
  if new_gps:
    command.append('-c')
    command.append('%.6f')
    latitude = float(new_gps[0])
    command.append('-GPSLatitude="%f"' % (abs(latitude)))
    if latitude >= 0.0:
      command.append('-GPSLatitudeRef=N')
    else:
      command.append('-GPSLatitudeRef=S')
    longitude = float(new_gps[1])
    command.append('-GPSLongitude="%f"' % (abs(longitude)))
    if longitude >= 0.0:
      command.append('-GPSLongitudeRef=E')
    else:
      command.append('-GPSLongitudeRef=W')
  command.append("-iptc:CodedCharacterSet=ESC % G")
  command.append(filepath)
  result = systemutils.execandcombine(command)
  if tmp:
    os.remove(tmp)
  if result == "1 image files updated":
    # wipe out the back file created by exiftool
    backup_file = filepath + "_original"
    if os.path.exists(backup_file):
      os.remove(backup_file)
    return True
  else:
    print >> sys.stderr, "Failed to update IPTC data in image %s: %s" % (
        filepath, result)
    return False
  
