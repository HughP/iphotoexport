#! /usr/bin/env python
"""Reads iPhoto library info, and exports photos and movies."""

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
import re
import shutil
import string
import sys
import unicodedata

from optparse import OptionParser

import appledata.iphotodata as iphotodata
import tilutil.exiftool as exiftool
import tilutil.systemutils as sysutils

# TODO: make this list configurable
_IGNORE_LIST = ("pspbrwse.jbf", "thumbs.db", "desktop.ini", ".ds_store",
                "ipod photo cache", "picasa.ini", ".picasa.ini", 
                "albumdata.xml", "albumdata2.xml", "pkginfo", "imovie data", 
                "dir.data", "iphoto.ipspot", "iphotolock.data", "library.data", 
                "library.iphoto", "library6.iphoto", "caches", ".ipspot_update",
                ".picasaoriginals")

def is_ignore(file_name):
  """returns True if the file name is in a list of names to ignore."""
  if file_name.startswith("._"):
    return True
  name = file_name.lower()
  return name in _IGNORE_LIST


def make_foldername(name):
  """Returns a valid folder name by replacing problematic characters."""
  result = ""
  for c in name:
    if c.isdigit() or c.isalpha() or c == "," or c == " ":
      result += c
    elif c == ':':
      result += "."
    elif c == '-':
      result += '-'
    else:
      result += '_'
  return result


def album_util_make_filename(name):
  """Returns a valid file name by replacing problematic characters."""
  result = u""
  for c in name:
    if c.isalpha() or c.isdigit() or c.isspace():
      result += c
    elif c == ":":
      result += '.'
    elif c == "/" or c == '-':
      result += '-'
    else:
      result += ' '
  return unicodedata.normalize("NFC", result)


def compare_keywords(new_keywords, old_keywords):
  """compares two lists of keywords, and returns True if they are the same."""
  if len(new_keywords) != len(old_keywords):
    return False
  for keyword in new_keywords:
    found_it = False
    for old_keyword in old_keywords:
      if old_keyword.strip() == keyword:
        found_it = True
        break
    if not found_it:
      return False
  return True


def delete_album_file(album_file, albumdirectory, msg, options):
  """sanity check - only delete from album directory."""
  if not album_file.startswith(albumdirectory):
    print >> sys.stderr, (
        "Internal error - attempting to delete file "
        "that is not in album directory:\n    %s") % (album_file)
    return False
  if msg:
    print "%s: %s" % (msg, album_file)

  if not options.delete:
    print "Invoke iphotoexport with the -d option to delete this file."
    return False
  
  try:
    if os.path.isdir(album_file):
      file_list = os.listdir(album_file)
      for subfile in file_list:
        delete_album_file(os.path.join(album_file, subfile), albumdirectory,
                          msg, options)
      os.rmdir(album_file)
    else:
      os.remove(album_file)
    return True
  except OSError, ex:
    print >> sys.stderr, "Could not delete %s: %s" % (album_file, ex)
  return False


def copy_or_link_file(source, target, options):
  """copies or links a file."""
  # looks at options.link and options.update
  try:
    mode = " (copy)"
    if options.link:
      mode = " (link)"
    if os.path.exists(target):
      if not options.update:
        print "Needs update: %s." % (target)
        print "Use the -u option to update this file." 
        return
      print "Updating: " + target + mode
      os.remove(target)
    else:
      print "New file: " + target + mode
    if options.link:
      os.link(source, target)
    else:
      # 'cp' is about 4x faster than shutil.copy2() when I tested it a long
      # time ago, but it requires a subprocess
      shutil.copy2(source, target)
      #result = sysutils.execandcombine('cp -fp "%s" "%s"' % (source, target))
      #if result:
      #  print >> sys.stderr, "%s: %s" % (source, result)
  except OSError, ose:
    print >> sys.stderr, "%s: %s" % (source, ose)


class ExportFile(object):
  """Describes an exported image."""

  def __init__(self, photo, export_directory, base_name):
    """Creates a new ExportFile object."""
    self.photo = photo
    self.export_directory = export_directory
    self.export_file = os.path.join(
        export_directory, 
        base_name + "." + sysutils.getfileextension(photo.getimagepath()))
    # location of "Original" file, if any
    self.original_export_file = os.path.join(
        export_directory, "Originals", base_name + "." +
        sysutils.getfileextension(photo.getimagepath()))

  def get_photo(self):
    """Gets the associated iPhotoImage."""
    return self.photo

  def generate(self, options):
    """makes sure all files exist in other album, and generates if necessary."""
    # check albumFile
    source_file = self.photo.getimagepath()
    do_export = False
    do_original_export = False

    try:
      if os.path.exists(self.export_file):
        if os.path.getmtime(self.export_file) < os.path.getmtime(source_file):
          do_export = True
      else:
        do_export = True

      if options.originals and self.photo.originalpath is not None:
        export_dir = os.path.split(self.original_export_file)[0]
        if not os.path.exists(export_dir):
          os.mkdir(export_dir)
        original_source_file = self.photo.originalpath
        if os.path.exists(self.original_export_file):
          if (os.path.getmtime(self.original_export_file) <
              os.path.getmtime(original_source_file)):
            do_original_export = True
        else:
          do_original_export = True

      # if we use links, we update the IPTC data in the original file
      do_iptc = (options.iptc == 1 and do_export) or options.iptc == 2
      if do_iptc and options.link:
        if self.check_iptc_data(source_file):
          do_export = True

      if do_export:
        copy_or_link_file(source_file, self.export_file, options)

      # if we copy, we update the IPTC data in the copied file
      if do_iptc and not options.link:
        self.check_iptc_data(self.export_file)

      if do_original_export:
        original_source_file = self.photo.originalpath
        if options.link:
          self.check_iptc_data(original_source_file)
        copy_or_link_file(original_source_file, self.original_export_file,
                          options)
        if not options.link:
          self.check_iptc_data(self.original_export_file)
    except OSError, ose:
      print >> sys.stderr, "Failed to export %s: %s" % (source_file, ose)

  def check_iptc_data(self, export_file):
    """Tests if a file has the proper keywords and caption in the meta data."""
    if not sysutils.getfileextension(export_file) in ("jpg", "tif", "png"):
      return False

    new_caption = self.photo.comment
    if new_caption is None:
      new_caption = ""
    else:
      new_caption = new_caption.strip()
    file_keywords, file_caption, date_time_original = exiftool.get_iptc_data(
        export_file)
    if not sysutils.equalscontent(file_caption, new_caption):
      print ('Updating IPTC for %s because it has Caption "%s" instead of '
             '"%s".') % (export_file, file_caption, new_caption)
    else:
      new_caption = None

    new_keywords = self.photo.keywords
    for keyword in self.photo.getfaces():
      if not keyword in new_keywords:
        new_keywords.append(keyword)
    if not compare_keywords(new_keywords, file_keywords):
      print "Updating IPTC for %s because of keywords (%s instead of %s)" % (
          export_file, ",".join(file_keywords), ",".join(new_keywords))
    else:
      new_keywords = None

    new_date = None
    if date_time_original != self.photo.date:
      print "Updating IPTC for %s because of date (%s instead of %s)" % (
          export_file, date_time_original, self.photo.date)
      new_date = self.photo.date
      
    if new_caption or new_keywords or new_date:
      exiftool.update_iptcdata(export_file, new_caption, new_keywords, 
                               new_date)
      return True
    return False

  def is_part_of(self, file_name):
    """Checks if <file> is part of this image."""
    return self.export_file == file_name

class ExportDirectory(object):
  """Tracks an album folder in the export location."""

  def __init__(self, name, iphoto_container, albumdirectory):
    self.name = name
    self.iphoto_container = iphoto_container
    self.albumdirectory = albumdirectory
    self.files = {}

  def process_albums(self, images, export_movies, name_template):
    """Works through an image folder tree, and builds data for exporting."""
    entries = 0
    template = string.Template(name_template)

    if images is not None:
      for image in images:
        if image.ismovie() and not export_movies:
          continue
        base_name = image.getcaption()
        album_basename = self.make_album_basename(base_name, entries + 1,
                                                  template)
        picture_file = ExportFile(image, self.albumdirectory, album_basename)
        self.files[album_basename] = picture_file
        entries += 1

    return entries

  def make_album_basename(self, orig_basename, index, name_template):
    """creates unique file name."""
    album_basename = None

    # default image caption filenames have the file extension on them already,
    # so remove it or the export filename will look like "IMG 0087 JPG.jpg"
    orig_basename = re.sub(re.compile(r'\.(jpeg|jpg|png|tif|tiff)$',
                                      re.IGNORECASE), '', orig_basename)
    formatted_name = name_template.safe_substitute({"index" : index, 
                                                    "caption" : orig_basename })
    base_name = album_util_make_filename(formatted_name)
    index = 0
    while True:
      album_basename = base_name
      if index > 0:
        album_basename += "_%d" % (index)
      if self.files.get(album_basename) is None:
        break
      index += 1
    return album_basename

  def load_album(self, options):
    """walks the album directory tree, and scans it for existing files."""
    if not os.path.exists(self.albumdirectory):
      os.makedirs(self.albumdirectory)
    file_list = os.listdir(self.albumdirectory)
    if file_list is None:
      return

    for f in file_list:
      # we won't touch some files
      if is_ignore(f):
        continue

      album_file = unicodedata.normalize("NFC", 
                                         os.path.join(self.albumdirectory, f))
      if os.path.isdir(album_file):
        if f == "Originals" and options.originals:
          self.scan_originals(album_file, options)
          continue
        else:
          delete_album_file(album_file, self.albumdirectory,
                            "Obsolete export directory", options)
          continue

      base_name = unicodedata.normalize("NFC", 
                                        sysutils.getfilebasename(album_file))
      master_file = self.files.get(base_name)

      # everything else must have a master, or will have to go
      if master_file is None or not master_file.is_part_of(album_file):
        delete_album_file(album_file, self.albumdirectory,
                        "Obsolete exported file", options)

  def scan_originals(self, folder, options):
    """Scan a folder of Original images, and delete obsolete ones."""
    file_list = os.listdir(folder)
    if file_list is None:
      return

    for f in file_list:
      # we won't touch some files
      if is_ignore(f):
        continue

      originalfile = os.path.join(folder, f)
      if os.path.isdir(originalfile):
        delete_album_file(originalfile, self.albumdirectory,
                        "Obsolete export Originals directory", options)
        continue

      base_name = unicodedata.normalize("NFC", 
                                        sysutils.getfilebasename(originalfile))
      master_file = self.files.get(base_name)

      # everything else must have a master, or will have to go
      if not master_file or not master_file.get_photo().originalpath:
        delete_album_file(originalfile, originalfile, "Obsolete Original",
                          options)

  def generate_files(self, options):
    """Generates the files in the export location."""
    if not os.path.exists(self.albumdirectory):
      os.makedirs(self.albumdirectory)
    sorted_files = []
    for f in self.files:
      sorted_files.append(f)
    sorted_files.sort()
    for f in sorted_files:
      self.files[f].generate(options)


class ExportLibrary(object):
  """The root of the export tree."""

  def __init__(self, albumdirectory):
    self.albumdirectory = albumdirectory
    self.named_folders = {}
    
  def _find_unused_folder(self, folder):
    """Returns a folder name based on folder that isn't used yet"""
    i = 0
    while True:
      if i > 0:
        proposed = "%s_(%d)" % (folder, i)
      else:
        proposed = folder
      if self.named_folders.get(proposed) is None:
        return proposed
      i += 1

  def process_albums(self, albums, album_types, folder_prefix, includes,
                     excludes, export_movies, name_template, matched=False):
    """Walks trough an iPhoto album tree, and discovers albums (directories)."""
    entries = 0

    include_pattern = re.compile(includes)
    exclude_pattern = None
    if excludes:
      exclude_pattern = re.compile(excludes)
      
    # first, do the sub-albums
    for sub_album in albums:
      sub_name = sub_album.name
      if not sub_name:
        print "Found an album with no name: " + sub_album.albumid
        sub_name = "xxx"

      # check the album type
      if sub_album.albumtype == "Folder":
        sub_matched = matched
        if include_pattern.match(sub_name):
          sub_matched = True
        self.process_albums(sub_album.albums, album_types,
                           folder_prefix + make_foldername(sub_name) + "/",
                           includes, excludes, export_movies, name_template,
                           sub_matched)
        continue
      elif (sub_album.albumtype == "None" or
            not sub_album.albumtype in album_types):
        # print "Ignoring " + sub_album.name + " of type " + \
        # sub_album.albumtype
        continue

      if not matched and not include_pattern.match(sub_name):
        continue

      if exclude_pattern and exclude_pattern.match(sub_name):
        continue

      folder_hint = sub_album.getfolderhint()
      prefix = folder_prefix
      if folder_hint is not None:
        prefix = prefix + make_foldername(folder_hint) + "/"
      sub_name = prefix + make_foldername(sub_name)
      sub_name = self._find_unused_folder(sub_name)

      # first, do the sub-albums
      if self.process_albums(sub_album.albums, album_types, folder_prefix,
                            includes, excludes, export_movies, name_template,
                            matched) > 0:
        entries += 1

      # now the album itself
      picture_directory = ExportDirectory(
          sub_name, sub_album, os.path.join(self.albumdirectory, sub_name))
      if picture_directory.process_albums(sub_album.images, export_movies,
                                          name_template) > 0:
        self.named_folders[sub_name] = picture_directory
        entries += 1

    return entries

  def load_album(self, options, exclude_folders):
    """Loads an existing album (export folder)."""
    if not os.path.exists(self.albumdirectory):
      os.makedirs(self.albumdirectory)

    album_directories = {}
    for f in self.named_folders:
      folder = self.named_folders[f]
      album_directories[folder.albumdirectory] = True
      folder.load_album(options)

    self.check_directories(self.albumdirectory, "", album_directories,
                           exclude_folders, options)

  def check_directories(self, directory, rel_path, album_directories,
                        exclude_folders, options):
    """Checks an export directory for obsolete files."""
    if os.path.split(directory)[1] in exclude_folders:
      return True
    contains_albums = False
    # passing a unicode directory name gives back unicode filenames, passing a
    # str directory name gives back str filenames. On MacOS, filenames come back
    # in Unicode Normalization Form D, so force to form C.
    file_list = [ unicodedata.normalize("NFC", nfd) 
                 for nfd in os.listdir(unicode(directory)) ]
    for f in file_list:
      album_file = os.path.join(directory, f)
      if os.path.isdir(album_file):
        if f == "iPod Photo Cache":
          print "Skipping " + album_file
          continue
        rel_path_file = os.path.join(rel_path, f)
        if album_directories.get(album_file):
          contains_albums = True
        elif not self.check_directories(album_file, rel_path_file,
                                        album_directories, exclude_folders,
                                        options):
          delete_album_file(album_file, directory, "Obsolete directory",
                            options)
      else:
        # we won't touch some files
        if is_ignore(f):
          continue
        delete_album_file(album_file, directory, "Obsolete", options)
    return contains_albums

  def generate_files(self, options):
    """Walks through the export tree and sync the files."""
    if not os.path.exists(self.albumdirectory):
      os.makedirs(self.albumdirectory)
    sorted_dirs = []
    for ndir in self.named_folders:
      sorted_dirs.append(ndir)
    sorted_dirs.sort()
    for key in sorted_dirs:
      self.named_folders[key].generate_files(options)

def export_iphoto(data, export_dir, excludes, exclude_folders, options):
  """Main routine for exporting iPhoto images."""

  print "Scanning iPhoto data for photos to export..."
  album = ExportLibrary(os.path.join(export_dir))
  if options.events is not None:
    album.process_albums(data.rolls, ["Event"], "", 
                         options.events, excludes, options.movies, 
                         options.nametemplate)

  if options.albums is not None:
    # ignore: Selected Event Album, Special Roll, Special Month
    album.process_albums(data.masteralbum.albums, ["Regular", "Published"], "",
                         options.albums, excludes, options.movies,
                         options.nametemplate)

  if options.smarts is not None:
    album.process_albums(data.masteralbum.albums, ["Smart"], "", 
                         options.smarts, excludes, options.movies,
                         options.nametemplate)

  print "Scanning existing files in export folder..."
  album.load_album(options, exclude_folders)

  print "Exporting photos from iPhoto to export folder..."
  album.generate_files(options)


USAGE = """usage: %prog [options] <iPhoto Library Location> <exportFolder>

Exports images and movies from an iPhoto library into a folder.

Arguments:
  <iPhoto Library Location>
      iPhoto Library package location. Typically "~/Pictures/iPhoto Library".

  <exportFolder>
      Folder to export the selected iPhoto images and movies into. Any files
      found in this folder that are not part of the export set will be
      deleted, and files that match will be overwritten if the iPhoto version
      of the file is different.
"""


def main():
  """main routine for iphotoexport."""
  
  parser = OptionParser(usage=USAGE)
  parser.add_option(
      "-a", "--albums", 
      help="""Export matching regular albums. The argument 
      is a regular expression. Use -a . to export all regular albums.""")
  parser.add_option(
      "-d", "--delete", action="store_true",
      help="Delete obsolete files that are no longer in your iPhoto library.")
  parser.add_option(
      "-e", "--events", 
      help="""Export matching events. The argument is
      a regular expression. Use -e . to export all events.""")
  parser.add_option("-f", "--faces", action="store_true",
                    help="Process faces information")
  parser.add_option(
      "-k", "--iptc", action="store_const", const=1, dest="iptc",
      help="""Check the IPTC data of all new or updated files. Checks for 
      keywords and descriptions. Requires the program "exiftool" (see
      http://www.sno.phy.queensu.ca/~phil/exiftool/).""")
  parser.add_option(
      "-K", "--iptcall", action="store_const", const=2, dest="iptc",
      help="""Check the IPTC data of all files. Checks for 
      keywords and descriptions. Requires the program "exiftool" (see
      http://www.sno.phy.queensu.ca/~phil/exiftool/).""")
  parser.add_option(
      "-l", "--link", action="store_true",
      help="""Use links instead of copying files. Use with care, as changes made
      to the exported files will affect the image that is stored in the iPhoto
      library.""")
  parser.add_option(
      "-n", "--nametemplate", default="${caption}",
      help="""Template for naming image files. Default: "${caption}".""")
  parser.add_option("-o", "--originals", action="store_true", 
                    help="Export original files into Originals.")
  parser.add_option("--pictures", action="store_false", dest="movies",
                    default=True, 
                    help="Export pictures only (no movies).")
  parser.add_option(
      "-s", "--smarts", 
      help="""Export matching smart albums. The argument 
      is a regular expression. Use -s . to export all smart albums.""")
  parser.add_option("-u", "--update", action="store_true",
                    help="Update existing files.")
  parser.add_option(
      "-x", "--exclude", 
      help="""Don't export matching albums or events. The pattern is a regular 
      expression.""")
  parser.add_option(
      "--excludefolders", 
      help="List of folders to ignore in the export folder (comma separated).")
  
  (options, args) = parser.parse_args()
  if len(args) != 2:
    parser.error("Incorrect number of arguments (expect 2, found %d)" %
                 (len(args)))
  library_dir = args[0]
  export_dir = args[1]
  
  if not options.albums and not options.events and not options.smarts:
    parser.error("Need to specify at least one event, album, or smart album.")
  if options.iptc > 0 and not exiftool.check_exif_tool():
    return 1
  
  album_xml_file = iphotodata.get_album_xmlfile(library_dir)
  data = iphotodata.get_iphoto_data(library_dir, album_xml_file, options.faces)
  exclude_folders = []
  if options.excludefolders:
    exclude_folders = options.excludefolders.split(",")
  
  export_iphoto(data, export_dir, options.exclude, exclude_folders, options)


if __name__ == "__main__":
  main()
