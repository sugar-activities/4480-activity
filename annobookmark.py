# Copyright 2009 One Laptop Per Child
# Author: Sayamindu Dasgupta <sayamindu@laptop.org>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import simplejson
#import cjson
import logging
import gconf
from sugar.graphics.xocolor import XoColor

_logger = logging.getLogger('anno-activity')


class Bookmark:
    def __init__(self, data):
        self.md5 = data[0]
        self.page_no = data[1]
        self.content = data[2]
        self.timestamp = data[3]
        self.nick = data[4]
        self.color = data[5]
        self.local = data[6]
        
    def belongstopage(self, page_no):
        return self.page_no == page_no 
    
    def is_local(self):
        return bool(self.local)

    def get_note_title(self):
        if self.content == '' or self.content is None:
            return ''

        note = simplejson.loads(self.content)
        #note = cjson.decode(self.content)

        return note['title']

    def get_note_body(self):
        if self.content == '' or self.content is None:
            return ''
        
        note = simplejson.loads(self.content)
        #note = cjson.decode(self.content)
        return note['body']
        



class AnnoBookmark:
    def __init__(self, data):
        self.id = data[0]
        self.md5 = data[1]
        self.page = data[2]
        self.title = data[3]
        self.content = data[4]
        self.bodyurl = data[5]
        self.texttitle = data[6]
        self.textcreator = data[7]
        self.created = data[8]
        self.modified = data[9]
        self.creator = data[10]
        self.annotates = data[11]

        if isinstance(data[12], str) or isinstance(data[12], unicode):
            self.color = XoColor(data[12])
        elif isinstance(data[12], XoColor):
            self.color = data[12]
        else:
            self.color = XoColor(" ")

        self.local = data[13]
        self.mimetype = data[14]
        self.uuid = data[15]
        self.annotationurl = data[16]
        if ( ( self.uuid == None ) or ( len( self.uuid ) == 0 ) ):
            self.make_new_uuid()
        _logger.debug('annobookmark annotates is %s' % self.annotates)

        if ( self.annotationurl == None ):
            self.annotationurl = ''

    
    def __str__(self):
        r  = str( "A bookmark: id: %s \nuuid: %s" % ( str( self.id ), self.uuid ) )
        r += str( "\nmd5: %s" % str( self.md5 ) )
        r += str( "\npage: %d\ntitle: %s" % ( self.page, self.title ) )
        r += str( "\ncontent: %s" % self.content ) 
        r += str( "\nbodyurl: %s \nannotationurl: %s" % ( self.bodyurl, self.annotationurl ) )
        r += str( "\ncreated: %s \nmodified: %s" % ( self.created, str( self.modified ) ) )
        r += str( "\ncreator: %s" % ( self.creator ) )
        r += str( "\nannotates: %s \nmimetype: %s" % ( self.annotates, self.mimetype ) )
        r += str( "\ncolor: %s \nlocal: %s" % ( str( self.color ), str( self.local ) ) )
        return r


    def make_new_uuid(self):
        if ( self.md5 != None ) and ( self.id != None ):
            self.uuid = "urn:sugaruuid:" + self.creator + "-" + self.md5 + "-" + str(self.id)


    def belongstopage(self, page):
        return self.page == page 
    
    def is_local(self):
        return bool(self.local)

    def set_note_title(self, note_title):
        self.title = note_title

    def get_note_title(self):
        if self.title == '' or self.title is None:
            return ''
        return self.title
    
    def set_note_body(self, note_content):
        self.content = note_content

    def get_note_body(self):
        if self.content == '' or self.content is None:
            return ''
        return self.content

    def get_id(self):
        return self.id

    def set_id(self, id):
        self.id = id

    def set_modified(self, modified):
        self.modified = modified

    def get_modified(self):
        return self.modified

    def get_page(self):
        return self.page

    def get_bodyurl(self):
        return self.bodyurl
		
    def set_bodyurl(self, url):
        self.bodyurl = url		

    def get_annotationurl(self):
        return self.annotationurl

    def set_annotationurl(self, url):
        self.annotationurl = url		

    def get_created(self):
        return self.created

    def get_creator(self):
        return self.creator

    def set_creator(self, creator):
        self.creator = creator    

    def get_target(self):
        return self.get_annotates()

    def get_annotates(self):
        return self.annotates

    def get_texttitle(self):
        return self.texttitle

    def set_texttitle(self, title):
        self.texttitle = title
 
    def get_textcreator(self):
        return self.texttitle

    def set_textcreator(self, creator):
        self.textcreator = creator
        
    def get_color(self):
        return self.color

    def get_mimetype(self):
        return self.mimetype

    def get_filehash(self):
        return self.md5

    def get_uuid(self): 
        return self.uuid 

    def get_json(self):
        arr = {
        'id' : self.id,
        'md5' : self.md5,
        'page' : self.page,
        'title' : self.title,
        'content' : self.content,
        'bodyurl' : self.bodyurl,
        'texttitle' : self.texttitle,
        'textcreator' : self.textcreator,
        'created' : self.created,
        'modified' : self.modified,
        'creator' : self.creator,
        'annotates' : self.annotates,
        'color' : self.color.to_string(),
        'local' : self.local,
        'mimetype' : self.mimetype,
        'uuid' : self.uuid,
        'annotationurl' : self.annotationurl
        }
        return simplejson.dumps(arr)
        #return cjson.encode(arr)
