'''
Created on May 29, 2009

@author: tilman
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

import filecmp
import os

def execandcombine(command):
  """execute a shell command, and return all output in a single string."""
  data = execandcapture(command)
  return "\n".join(data)


def execandcapture(command):
  """execute a shell command, and return output lines in a sequence."""
  pipe = os.popen(command)
  data = []
  while True:
    line = pipe.readline()
    if not line:
      break
    line = line.strip()
    line = line.replace("\r", "\n")
    data.append(line)
  pipe.close()
  return data

def equalscontent(string1, string2):
  """Tests if two strings are equal.
  
  None is treated like an empty string. Trailing and leading whitespace is
  ignored."""
  if not string1:
    string1 = ""
  if not string2:
    string2 = ""
  return string1.strip() == string2.strip()

# FileUtil --------------------------------------------------------------------


def getfilebasename(file_path):
  """returns the name of a file, without the extension. "/a/b/c.txt" -> "c"."""
  return os.path.basename(os.path.splitext(file_path)[0])


def getfileextension(file_path):
  """returns the extension of a file, e.g. '/a/b/c.txt' -> 'txt'."""
  ext = os.path.splitext(file_path)[1]
  if ext.startswith("."):
    ext = ext[1:]
  return ext.lower()


def issamefile(file1, file2):
  """Tests if the two files have the same contents."""
  return filecmp.cmp(file1, file2, False)