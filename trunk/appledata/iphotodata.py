'''iPhoto database: reads iPhoto database and parses it into albums and images.

Created on May 29, 2009

@author: tsporkert@gmail.com

This class reads iPhoto image, event, album information from the file 
AlbumData.xml in the iPhoto library directory. That file is written by iPhoto
for the media browser in other applications. The class also reads faces 
information from the iPhoto face Sqlite database in faces.db. All data are
organized in the class IPhotoData. Images in iPhoto are grouped using events
(formerly knows as rolls) and albums. Each image is in exactly one event, and
optionally, in zero or more albums. Albums can be nested (folders). The album
types are: 
Folder - contains other albums
Published - an album publishe to MobileMe
Regular - a regular user created album
SelectedEventAlbum - most recent album (as shown in iPhoto)
Shelf - list of flagged images
Smart - a user created smart album
SpecialMonth - "Last Month"
SpecialRoll -  "Last Import"
Event - this type does not exist in the XML file, but we use it in this code
        to allow us to treat events just like any other album 
None - should not really happen
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

import os
import sys

try:
  # Not all systems have sqlite3 available
  import sqlite3
except ImportError, e:
  # save the error, so we can raise it later if we actually need the module
  sqlite_error = e
  
import appledata.applexml as applexml
import tilutil.systemutils as sysutils


class IPhotoData(object):
  """top level iPhoto data node."""

  def __init__(self, xml_data):
    """# call with results of readAppleXML."""
    self._data = xml_data

    self.albums = {}
    
    self.keywords = {}  # Master map of keywords
    keyword_list = self._data.get("List of Keywords")
    for key in keyword_list:
      self.keywords[key] = keyword_list.get(key)

    self.images_by_id = {}
    image_data = self._data.get("Master Image List")
    if image_data is not None:
      for key in image_data:
        image = IPhotoImage(image_data.get(key), self.keywords)
        self.images_by_id[key] = image

    album_data = self._data.get("List of Albums")
  
    self.master_album = None
    for data in album_data:
      album = IPhotoAlbum(data, self.images_by_id, self.albums,
                          self.master_album)
      self.albums[album.albumid] = album
      if album.master:
        self.master_album = album

    roll_data = self._data.get("List of Rolls")
    self._rolls = {}
    for roll in roll_data:
      roll = IPhotoRoll(roll, self.images_by_id)
      self._rolls[roll.albumid] = roll

    # TODO(tilman): do this work only on demand, for ScanObsolete or 
    # checkUnqiueTitles
    self.images_by_base_name = {}
    self.images_by_file_name = {}

    # build the basename map
    for image in self.images_by_id.values():
      base_name = image.getbasename()
      other_images = self.images_by_base_name.get(base_name)
      if other_images is None:
        other_images = []
        self.images_by_base_name[base_name] = other_images
      other_images.append(image)

      other_image_list = self.images_by_file_name.get(image.getimagename())
      if other_image_list is None:
        other_image_list = []
        self.images_by_file_name[image.getimagename()] = other_image_list
      other_image_list.append(image)

    self.face_names = {}
    self.place_names = {}
    self.user_places = {}

  def _getapplicationversion(self):
    return self._data.get("Application Version")
  applicationVersion = property(_getapplicationversion, doc='iPhoto version')

  def _getmasteralbum(self):
    return self.master_album
  masteralbum = property(_getmasteralbum, doc="main (master) album")

  def _getimages(self):
    return self.images_by_id.values()
  images = property(_getimages, "List of images")

  def _getrolls(self):
    return self._rolls.values()
  rolls = property(_getrolls, "List of rolls (events)")

  def getbaseimages(self, base_name):
    """returns an IPhotoImage list of all images with a matching base name."""
    return self.images_by_base_name.get(base_name)

  def getnamedimage(self, file_name):
    """returns an IPhotoImage for the given file name."""
    image_list = self.images_by_file_name.get(file_name)
    if image_list:
      return image_list[0]
    return None

  def getallimages(self):
    """returns map from full path name to image."""
    image_map = {}
    for image in self.images_by_id.values():
      image_map[image.GetImagePath()] = image
      image_map[image.thumbpath] = image
      if image.originalpath is not None:
        image_map[image.originalpath] = image
    return image_map

  def checkalbumsizes(self, max_size):
    """Prints a message for any event or album that has too many images."""
    messages = []
    for album in self._rolls.values():
      if album.size > max_size:
        messages.append("%s: event too large (%d)" % (album.name, album.size))
    for album in self.albums.values():
      if album.albumtype == "Regular" and album.size > max_size:
        messages.append("%s: album too large (%d)" % (album.name, album.size))
    messages.sort()
    for message in messages:
      print message


#  public void checkComments() {
#    TreeSet<String> images = new TreeSet<String>();
#    for (IPhotoImage image : images_by_id.values()) {
#      String comment = image.GetComment();
#      if ((comment == null or comment.length() == 0) && !image.IsHidden())
#        images.add(image.getcaption());
#    }
#    for (String caption : images)
#      System.out.println(caption + ": missing comment.");
#  }

  def check_inalbums(self):
    """Checks that all images are in albums according to their events."""
    messages = []
    for image in self.images_by_id.values():
      if image.IsHidden():
        continue
      roll_name = self._rolls[image.roll].name
      albums = []
      in_album = False

      for album in image.GetAlbums():
        album_name = album.name
        if album.GetAlbumType == "Regular":
          albums.append(album.name)
          in_album = True
          if album_name != roll_name:
            messages.append(image.getcaption() + ": in wrong album (" +
                            roll_name + " vs. " + album_name + ").")
        elif (album.isSmart() and album_name.endswith(" Collection") or
              album_name == "People" or album_name == "Unorganized"):
          in_album = True
      if not in_album:
        messages.append(image.getcaption() + ": not in any album.")
      if albums:
        messages.append(image.getcaption() + ": in more than one album: " +
                        " ".join(albums))
    messages.sort()
    for message in messages:
      print message

  def readfaces(self, library_dir):
    """Reads faces information from face.db."""
    if sqlite_error:
      raise sqlite_error
    connection = sqlite3.connect(os.path.join(library_dir, "face.db"))
    cursor = connection.cursor()
    cursor.execute("SELECT face_key, name FROM face_name WHERE name != ''")
    for row in cursor:
      face_key, name = row
      self.face_names[face_key] = name

    cursor.execute(
        "SELECT image_key, face_key FROM detected_face")
    for row in cursor:
      image_key, face_key = row
      name = self.face_names.get(face_key)
      if name is None:
        continue
      image = self.images_by_id.get(str(image_key))
      if image is not None:
        image.addface(name)
    cursor.close()
    connection.close()
    
  def _checkplace(self, image, place_key):
    if place_key > 0:
      place_name = self.place_names.get(place_key)
      if place_name:
        image.placenames.append(place_name)
      else:
        print >> sys.stderr, "No place name found for %d" % (place_key)
      
  def readplaces(self, library_dir):
    """Reads places information from iPhotoMain.db"""
    if sqlite_error:
      raise sqlite_error
    connection = sqlite3.connect(os.path.join(library_dir, "iPhotoMain.db"))
    cursor = connection.cursor()
    cursor.execute("SELECT primaryKey, name FROM sqUserPlace")
    for row in cursor:
      place_key, name = row
      self.user_places[place_key] = name
      
    cursor.execute(('SELECT n.place, n.string FROM SqPlace p, SqPlaceName n '
                    'WHERE p.defaultName = n.primaryKey'))
    for row in cursor:
      place_key, name = row
      self.place_names[place_key] = name

    cursor.execute("SELECT primaryKey, gpsLatitude, gpsLongitude, " +
                   "namedPlace, ocean, country, province, county, " +
                   "city, neighborhood " +
                   "FROM SqPhotoInfo " +
                   "WHERE isVisible == 1 AND " +
                   "(manualLocation == 1 OR namedPlace > 0)")
    for row in cursor:
      (image_key, gps_latitude, gps_longitude, place_key, ocean, country, 
       province, county, city, neighborhood) = row
      name = self.user_places.get(place_key)
      image = self.images_by_id.get(str(image_key))
      if not image:
        print >> sys.stderr, "Couldn't find image for %d" % (image_key)
        continue
      if name:
        image.placenames.append(name)
      self._checkplace(image, ocean)
      self._checkplace(image, country)
      self._checkplace(image, province)
      self._checkplace(image, county)
      self._checkplace(image, city)
      self._checkplace(image, neighborhood)
        
      if abs(gps_latitude) <= 90 and abs(gps_longitude) <= 180:
        image.gps = (float("%.6f" % (gps_latitude)), 
                     float("%.6f" % (gps_longitude)))

    cursor.close()
    connection.close()
    
class IPhotoImage(object):
  """Describes an image in the iPhoto database."""

  def __init__(self, data, keyword_map):
    self.data = data
    self.caption = data.get("Caption")
    self.comment = data.get("Comment")
    self.date = applexml.getappletime(data.get("DateAsTimerInterval"))
    self.image_path = data.get("ImagePath")
    self.rating = int(data.get("Rating"))

    self.keywords = []
    keyword_list = data.get("Keywords")
    if keyword_list is not None:
      for i in keyword_list:
        self.keywords.append(keyword_map.get(i))

    self.originalpath = data.get("OriginalPath")
    self.roll = data.get("Roll")

    self.albums = []  # list of albums that this image belongs to
    self.faces = []
    self.placenames = []
    self.gps = None
    
  def getimagepath(self):
    """Returns the full path to this image.."""
    return self.image_path

  def getimagename(self):
    """Returns the file name of this image.."""
    name = os.path.split(self.image_path)[1]
    return name

  def getbasename(self):
    """Returns the base name of the main image file."""
    return sysutils.getfilebasename(self.image_path)

  def getcaption(self):
    """gets the caption (title) of the image."""
    if not self.caption:
      return self.getimagename()
    return self.caption

  def ismovie(self):
    """Tests if this image is a movie."""
    return self.data.get("MediaType") == "Movie"

  def addalbum(self, album):
    """Adds an album to the list of albums for this image."""
    self.albums.append(album)

  def addface(self, name):
    """Adds a face (name) to the list of faces for this image."""
    self.faces.append(name)

  def getfaces(self):
    """Gets the list of face tags for this image."""
    return self.faces

  def ishidden(self):
    """Tests if the image is hidden (using keyword "Hidden")"""
    return "Hidden" in self.keywords

  def _getthumbpath(self):
    return self.data.get("ThumbPath")
  thumbpath = property(_getthumbpath, doc="Path to thumbnail image")
  

class IPhotoContainer(object):
  """Base class for IPhotoAlbum and IPhotoRoll."""

  def __init__(self, data, albumtype, master, images):
    self.data = data
  
    self.name = ""
    self.albumtype = albumtype
    self.albumid = -1
    self.images = []
    self.albums = []
    self.master = master
    
    if not self.isfolder():
      keylist = data.get("KeyList")
      for key in keylist:
        image = images.get(key)
        if image:
          self.images.append(image)
        else:
          print "%s: image with id %s does not exist." % (self.tostring(), key)

  def _getcomment(self):
    return self.data.get("Comments")
  comment = property(_getcomment, doc='comments (description)')
  
  def _getsize(self):
    return len(self.images)
  size = property(_getsize, "Gets the size (# of images) of this album.")
  
  def isfolder(self):
    """tests if this album is a folder."""
    return "Folder" == self.albumtype

  def getfolderhint(self):
    """Gets a suggested folder name from comments."""
    if self.comment:
      for comment in self.comment.split("\n"):
        if comment.startswith("@"):
          return comment[1:]
    return None
  
  def getcommentwithouthints(self):
    """Gets the image comments, with any folder hint lines removed"""
    result = []
    if self.comment:
      for line in self.comment.split("\n"):
        if not line.startswith("@"):
          result.append(line)
    return "\n".join(result)
  
  def addalbum(self, album):
    """adds an album to this container."""
    self.albums.append(album)
  
  def tostring(self):
    """Gets a string that describes this album or event."""
    return "%s (%s)" % (self.name, self.albumtype)


class IPhotoRoll(IPhotoContainer):
  """Describes an iPhoto Roll or Event."""

  def __init__(self, data, images):
    IPhotoContainer.__init__(self, data, "Event", False, images)
    self.albumid = data.get("RollID")
    if not self.albumid:
      self.albumid = data.get("AlbumID")
    self.name = data.get("RollName")
    if not self.name:
      self.name = data.get("AlbumName")
        
  def _getdate(self):
    return applexml.getappletime(self.data.get("RollDateAsTimerInterval"))
  date = property(_getdate, doc="Date of event.")

 
class IPhotoAlbum(IPhotoContainer):
  """Describes an iPhoto Album."""

  def __init__(self, data, images, album_map, master_album):
    IPhotoContainer.__init__(self, data, data.get("Album Type"), 
                             data.get("Master"), images)
    self.albumid = data.get("AlbumId")
    self.name = data.get("AlbumName")

    parent_id = data.get("Parent")
    if parent_id is None:
      parent_id = -1
      self.parent = master_album
    else:
      self.parent = album_map.get(parent_id)
    if self.parent is None:
      if not self.master:
        print "Album %s: parent with id %d not found." % (
            self.name, parent_id)
    else:
      self.parent.addalbum(self)


##     public Date getDate() {
##         Date albumDate = new Date()
##         for (IPhotoImage image : keyList)
##             if (image.getDate().before(albumDate))
##                 albumDate = image.getDate()
##         return albumDate
##     }

def get_album_xmlfile(library_dir):
  """Locates the iPhoto AlbumData.xml file."""
  if os.path.exists(library_dir) and os.path.isdir(library_dir):
    album_xml_file = os.path.join(library_dir, "AlbumData.xml")
    if os.path.exists(album_xml_file):
      return album_xml_file
  raise ValueError, ("%s does not appear to be a valid iPhoto library "
      "location.") % (library_dir)
 

def get_iphoto_data(library_dir, album_xml_file, do_faces, do_places):
  """reads the iPhoto database and converts it into an iPhotoData object."""
  print "Reading iPhoto database..."
  album_xml = applexml.read_applexml(album_xml_file)

  print "Converting iPhoto data..."
  data = IPhotoData(album_xml)
  if (not data.applicationVersion.startswith("8.") and
      not data.applicationVersion.startswith("7.") and
      not data.applicationVersion.startswith("6.")):
    raise ValueError, "iPhoto version %s not supported" % (
        data.applicationVersion)

  if do_faces:
    if data.applicationVersion.startswith("8."):
      print "Reading faces..."
      data.readfaces(library_dir)
    else:
      print >> sys.stderr, "No face information in this iPhoto library."
      
  if do_places:
    if data.applicationVersion.startswith("8."):
      print "Reading places..."
      data.readplaces(library_dir)
    else:
      print >> sys.stderr, "No place information in this iPhoto library."

  return data
