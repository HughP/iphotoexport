#! /usr/bin/env python
"""Utilities for the Picasa desktop application."""

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

import os
import sys
import unicodedata

from optparse import OptionParser
from xml.dom import minidom
from xml import parsers

import tilutil.exiftool as exiftool
import tilutil.systemutils as su

def get_picasa_folder_data(folder):
  """Looks for the .picasa.ini file in the folder, and returns the contents
     as a map. The keys are the image names, or "Picasa" for folder level
     information. The values are key-value pairs for each item."""

  picasa_data = {}
  path = os.path.join(folder, ".picasa.ini")
  if os.path.exists(path):
    f = open(path)
    item_data = {}
    for line in f:
      line = su.fsdec(line).strip()
      if line.startswith("[") and line.endswith("]"):
        key = line[1:len(line) - 1]
        item_data = {}
        picasa_data[key] = item_data
      elif line.find("=") != -1:
        parts = line.split("=")
        item_data[parts[0]] = parts[1]
    f.close()
  
  return picasa_data

def get_picasa_data_value(picasa_folder_data, section, key, default=""):
  """Returns the value for a key in a secion of Picasa folder data (from
     get_picasa_folder_data)"""
  section_data = picasa_folder_data.get(section)
  if not section_data:
    return default
  value = section_data.get(key)
  if not value:
    return default
  return value

def get_picasa_contacts(alt_files=None):
  """Reads the Picasa contacts.xml file, and returns a map from id to
     nick name. Merges in data from alternate files."""
  contacts_path = os.path.join(os.environ.get('HOME'),
      "Library/Application Support/Google/Picasa3/contacts/contacts.xml")
  if not os.path.exists(contacts_path):
    raise IOError, "Picasa contacts file not found at " + contacts_path
  contacts = {}
  _parse_picasa_contacts(contacts_path, contacts)
  if alt_files:
    for alt_file in alt_files:
      _parse_picasa_contacts(alt_file, contacts)
  return contacts

def _parse_picasa_contacts(contacts_path, contacts):
  """Reads a Picasa contacts XML file, and adds it to the contacts map.
     Will not overwrite existing entries."""
  try: 
    xml_data = minidom.parse(contacts_path)
    for xml_contacts in xml_data.getElementsByTagName("contacts"):
      for xml_contact in xml_contacts.getElementsByTagName("contact"):
        face_id = xml_contact.getAttribute("id")
        if not contacts.get(face_id):
          nick_name = xml_contact.getAttribute("display")
          if not nick_name:
            # no display name -> fall back on full name
            nick_name = xml_contact.getAttribute("name")
          contacts[face_id] = nick_name
    xml_data.unlink()
  except parsers.expat.ExpatError, ex:
    print >> sys.stderr, "Could not parse contacts database %s: %s" % (
        contacts_path, ex)

def check_face_keywords(path, faces):
  """Checks the keywords of an image, and makes sure all the faces are 
     listed."""
  (file_keywords, _caption, _date_time_original, _rating, 
      _gps) = exiftool.get_iptc_data(path)
  needs_update = False
  for face in faces:
    if not face in file_keywords:
      print su.fsenc(path) + " is missing " + face
      file_keywords.append(face)
      needs_update = True
      
  if needs_update:
    new_keywords = []
    for keyword in file_keywords:
      new_keywords.append(su.fsenc(keyword))
    exiftool.update_iptcdata(path, None, file_keywords, None, None, None)
  
  
def process_face_keywords(folder, contacts):
  """Works through a folder tree, and checks all images for face keywords"""
  file_list = os.listdir(folder)
  if file_list is None:
    return
  
  picasa_folder_data = get_picasa_folder_data(folder)
  
  for file_name in file_list:
    path = unicodedata.normalize("NFC", os.path.join(folder, file_name))
    if os.path.isdir(path):
      process_face_keywords(path, contacts)
      continue
    
    face_list = get_picasa_data_value(picasa_folder_data, file_name, "faces")
    if not face_list:
      continue
    
    faces = []
    for face in face_list.split(";"):
      (_rect, face_id) = face.split(',')
      nick_name = contacts.get(face_id)
      if nick_name:
        faces.append(nick_name)
      else:
        print >> sys.stderr, "%s: could not look up name for face id %s" % (
            path, face_id)
      
    if faces:
      check_face_keywords(path, faces)
    
  

USAGE = """usage: %prog [options]

Maintains metadata for images managed with Picasa.
"""


def main():
  """main routine for picasautil."""
  
  parser = OptionParser(usage=USAGE)
  parser.add_option(
      "-f", "--folder", 
      help="""Root of folder tree to process.""")
  parser.add_option(
      "--facekeywords", action="store_true",
      help="Copy face nick names to image keywords")
  
  (options, args) = parser.parse_args()
  if len(args) != 0:
    parser.error("Incorrect number of arguments (expect 0, found %d)" %
                 (len(args)))

  if not options.facekeywords:
    print >> sys.stderr, "Please specify an operation like --facekeywords."
    return 2
  
  if options.facekeywords and not exiftool.check_exif_tool():
    print >> sys.stderr, ("Exiftool is needed for the --itpc or --iptcall " +
                          "options.")
    return 1

  if options.facekeywords:
    if not options.folder:
      print >> sys.stderr, "Please use --folder to specify a root folder."
      return 1

    contacts = get_picasa_contacts()
    process_face_keywords(options.folder.decode(sys.getfilesystemencoding()),
                          contacts)

if __name__ == "__main__":
  main()
