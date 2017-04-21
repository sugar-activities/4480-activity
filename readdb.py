# Copyright 2009 One Laptop Per Child
# Author: Andreas Gros <info@andreasgros.net>, Sayamindu Dasgupta <sayamindu@laptop.org>
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

import logging

import os, os.path
import shutil
import sqlite3
import random
import hashlib
import time
import gconf
import simplejson
#import cjson
import urllib, urllib2
import re
from xml.dom import minidom
from sugar.datastore import datastore
from sugar import mime
from annobookmark import AnnoBookmark, Bookmark
from sugar.graphics.xocolor import XoColor


_logger = logging.getLogger('anno-activity')

def _init_db():
    dbdir = os.path.join(os.environ['SUGAR_ACTIVITY_ROOT'], 'data')
    dbpath = os.path.join(dbdir, 'anno_v1.db')

    srcpath = os.path.join(os.environ['SUGAR_BUNDLE_PATH'], 'anno_v1.db')

    #Situation 0: Db is existent
    if os.path.exists(dbpath):
        conn = sqlite3.connect(dbpath)
        conn.execute("CREATE TABLE IF NOT EXISTS deleted_annotations (id INTEGER PRIMARY KEY, uuid)")
        conn.commit()
        return dbpath

    #Situation 1: DB is non-existent at all
    if not os.path.exists(dbpath):
        try:
            os.makedirs(dbdir)
        except:
            pass
        shutil.copy(srcpath, dbpath)
        return dbpath
    
    
    #Situation 2: DB is outdated
    """
    if not os.path.exists(dbpath):
        conn = sqlite3.connect(dbpath)

        conn.execute("DROP TABLE annotations")
        conn.execute("CREATE TABLE annotations (id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)")
        
        conn.execute("CREATE TABLE annuserid (username, userid)")
        conn.commit()

        conn.close()
        return dbpath
    """
    # Should not reach this point
    return None

def _init_db_highlights(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS HIGHLIGHTS ' +
                '(md5 TEXT, page INTEGER, ' +
                'init_pos INTEGER, end_pos INTEGER)')
    conn.commit()





class BookmarkManager:
    def __init__(self, filehash):
        self._filehash = filehash

        dbpath = _init_db()

        assert dbpath != None

        self._conn = sqlite3.connect(dbpath)
        self._conn.text_factory = lambda x: unicode(x, "utf-8", "ignore")

        self._bookmarks = []
        self._populate_bookmarks()
        
    def add_bookmark(self, page, content, local=1):
        # locale = 0 means that this is a bookmark originally 
        # created by the person who originally shared the file
        timestamp = time.time()
        client = gconf.client_get_default()
        user = client.get_string("/desktop/sugar/user/nick")
        color = client.get_string("/desktop/sugar/user/color")

        t = (self._filehash, page, content, timestamp, user, color, local)
        self._conn.execute('insert into bookmarks values (?, ?, ?, ?, ?, ?, ?)', t)
        self._conn.commit()
        
        self._resync_bookmark_cache()
       


    def del_bookmark(self, page):
        client = gconf.client_get_default()
        user = client.get_string("/desktop/sugar/user/nick")

        t = (self._filehash, page, user)
        self._conn.execute('delete from bookmarks where md5=? and page=? and user=?', t)
        self._conn.commit()
        
        self._resync_bookmark_cache()



    def _populate_bookmarks(self):
        # TODO: Figure out if caching the entire set of bookmarks is a good idea or not
        rows = self._conn.execute('select * from bookmarks where md5=? order by page', (self._filehash,))

        for row in rows:
            self._bookmarks.append(Bookmark(row))
            
    def get_bookmarks_for_page(self, page):
        bookmarks = []
        for bookmark in self._bookmarks:
            if bookmark.belongstopage(page):
                bookmarks.append(bookmark)
        
        return bookmarks
    
    def _resync_bookmark_cache(self):
        # To be called when a new bookmark has been added/removed
        self._bookmarks = []
        self._populate_bookmarks()


    def get_prev_bookmark_for_page(self, page, wrap = True):
        if not len(self._bookmarks):
            return None
        
        if page <= self._bookmarks[0].page and wrap:
            return self._bookmarks[-1]
        else:
            for i in range(page-1, -1, -1):
                for bookmark in self._bookmarks:
                    if bookmark.belongstopage(i):
                        return bookmark
                
        return None 


    def get_next_bookmark_for_page(self, page, wrap = True):
        if not len(self._bookmarks):
            return None
        
        if page >= self._bookmarks[-1].page and wrap:
            return self._bookmarks[0]
        else:
            for i in range(page+1, self._bookmarks[-1].page + 1):
                for bookmark in self._bookmarks:
                    if bookmark.belongstopage(i):
                        return bookmark
        
        return None       


#/////////////////////////////////////
#working on: upon update of an annotation, all annotations are deleted and new one's created => needs to be fixed

class AnnotationManager:


    def __init__(self, filehash, mimetype, sidebar):
        self._sidebar = sidebar
        self.current_annotation = None
        self._userid = ''
        self._filehash = filehash
        self._texttitle = '' 
        self._textcreator = ''
        self._uuid = filehash
        self._mimetype = mimetype
        self._annotitle = ''
        self._content = ''
        self._color = ''
        self._local = ''
        self._annotations = []
        self._fileformat = 'image/svg+xml'
        self._annotates = ''
        self._creator = ''
        self._created = ''
        self._annotationurl = ''
        self._bodyurl = ''
        self._annotates = ''
        self._modified = '' 
        self._bodysvg = '' 
        self._id = ''
        self.modifiedtolerance = 10
        #self._annotationserver='http://localhost/anno/index.php'
        self._annotationserver='http://anno.treehouse.su/anno/index.php'
        #self._annotationserver='http://www.andreasgros.net/wp-content/plugins/annotation/annotation.php'
        self.get_etext_metadata()
        self._to_delete = []

        self._annojson = ''
        self.remotecreators = []
        self.remotecolors = {}
        self._highlights = {}
        dbpath = _init_db()

        assert dbpath != None

        self._conn = sqlite3.connect(dbpath)

        _init_db_highlights(self._conn)

        self._conn.text_factory = lambda x: unicode(x, 'utf-8', 'ignore')
        self._annotations = []
        self._populate_annotations()
        
  
    def get_highlights(self, page):
        try:
            return self._highlights[page]
        except KeyError:
            self._highlights[page] = []
            return self._highlights[page]



    def add_highlight(self, page, highlight_tuple):
        logging.error('Adding hg page %d %s' % (page, highlight_tuple))
        self.get_highlights(page).append(highlight_tuple)

        t = (self._filehash, page, highlight_tuple[0],
                highlight_tuple[1])
        self._conn.execute('insert into highlights values ' + \
                '(?, ?, ?, ?)', t)
        self._conn.commit()

    def del_highlight(self, page, highlight_tuple):
        self._highlights[page].remove(highlight_tuple)
        t = (self._filehash, page, highlight_tuple[0], \
                highlight_tuple[1])
        self._conn.execute('delete from highlights ' + \
            'where md5=? and page=? and init_pos=? and end_pos=?', \
            t)
        self._conn.commit()

    def _populate_highlights(self):
        rows = self._conn.execute('select * from highlights ' + \
            'where md5=? order by page', (self._filehash, ))
        for row in rows:
            page = row[1]
            init_pos = row[2]
            end_pos = row[3]
            highlight_tuple = [init_pos, end_pos]
            self.get_highlights(page).append(highlight_tuple)


    def get_userid_for_username(self, user):
        needsupdate = False
        needsinsert = False
        userid = ''
        rows = self._conn.execute('select userid from annuserid where username=?', (user, ))
        if ( rows != None ):
            r = rows.fetchone()
            if ( r != None ):
                if ( len(r[0]) > 0 ):
                    userid = r[0]
                else:
                    needsupdate = True
            else:
                needsinsert = True
        if ( rows == None ) or needsupdate or needsinsert:  
            url = self._annotationserver
            values = {'getidforuser' : user}
            try:
                data = urllib.urlencode(values)          
                req = urllib2.Request(url, data)
                response = urllib2.urlopen(req)
                jsonstr = response.read()
                _logger.debug("\n\ngot this userid json %s\n\n" % jsonstr )
                json_arr = simplejson.loads( jsonstr ) 
                _logger.debug("userid - json_arr %s" % json_arr )
                userid = json_arr['userid']
                _logger.debug("\nuserid is %s\n\n" % userid)
            except Exception, detail: 
                _logger.debug("userid fetching failed; detail: %s ", detail)
            if not needsupdate or needsinsert:
                _logger.debug('insert user, userid %s', str((user, userid)))
                self._conn.execute( 'insert into annuserid values (?, ?)', (user, userid) ) 
            else:               
                _logger.debug('updating userid %s', userid)
                self._conn.execute( 'update annuserid set userid=? where username=?', ( userid, user ) )
            self._conn.commit()
        _logger.debug('userid: found %s', userid)
        return userid

        
    def add_annotation(self, page, content, local=1):
        # locale = 0 means that this is a bookmark originally 
        # created by the person who originally shared the file
        self._created = time.time()
        self._modified = self._created
        client = gconf.client_get_default()
        user = client.get_string("/desktop/sugar/user/nick")
        color = client.get_string("/desktop/sugar/user/color")
        self._color = color
        _logger.debug('got this color: %s' % color)
        if self._userid == '':
            self._userid = self.get_userid_for_username( self.get_user_string( user ) )
        
        note = simplejson.loads(content)
        #note = cjson.decode(content)
        self._annotitle = note['title']
        self._content = note['body']
        self._creator = self._userid

        #check the last id from the database store
        row = self._conn.execute('select id from annotations order by id desc limit 1')
        aid = 0
        r = row.fetchone() 
        if r != None:
            aid = int(r[0]) + 1

        #(id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)
        t = (aid, self._filehash, page, self._annotitle, self._content, self._bodyurl, self._texttitle, self._textcreator, self._created, self._modified, self._userid, self._annotates, self._color, self._local, self._mimetype, None, None)
        annotation = AnnoBookmark(t)

        self._annojson = annotation.get_json()
        #(id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)
        t = (aid, self._filehash, page, self._annotitle, self._content, self._bodyurl, self._texttitle, self._textcreator,  self._created, self._modified, self._creator, self._annotates, self._color, self._local, self._mimetype, annotation.get_uuid(), None)
        self._conn.execute('insert into annotations values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', t)
        self._conn.commit()
        self._resync_annotation_cache()
        self.current_annotation = self._annotations[-1]
       


    
    def edit_annotation(self, page, content, annotation_id, local=1):
        # local = 0 means that this is a bookmark originally 
        # created by the person who originally shared the file
        print 'edit annotation called'
        note = simplejson.loads(content)
        #note = cjson.decode(content)
        annotitle = note['title']
        annocontent = note['body']

        for a in self._annotations:
            if a.get_id() == annotation_id:
                if ( a.get_note_title() != annotitle ) or ( a.get_note_body() != annocontent ):
                    a.set_modified(time.time())
                    a.set_note_title(annotitle)
                    a.set_note_body(annocontent)
                    self.update_annotation_db_record(a)
                    break
        



    def del_annotation(self, annotation_id):
        client = gconf.client_get_default()
        user = client.get_string("/desktop/sugar/user/nick")
        if self._userid == '':
            self._userid = self.get_userid_for_username( self.get_user_string( user ) )
        #get the clientuuid to schedule its deletion on the annotation server
        _logger.debug('delete annotation with id %s', str(annotation_id) )

        rows = self._conn.execute('select uuid, creator from annotations where md5=? and id=?', [self._filehash, annotation_id])
        row = rows.fetchone()
        if row[1] == self._userid:
            self._to_delete.append(row[0])
            _logger.debug(str('schedule annotation %s for deletion' % str(row)))
        else:
            self._conn.execute('insert into deleted_annotations values (?, ?)', (None, row[0]))
        t = (self._filehash, annotation_id)
        _logger.debug(str('t for deletion is %s' % str(t)))
        self._conn.execute('delete from annotations where md5=? and id=?', t)
        check = self._conn.commit()
        _logger.debug('deletion check %s ', str(check))
        self._resync_annotation_cache()




    def _populate_annotations(self):
        # TODO: Figure out if caching the entire set of annotations is a good idea or not
        #(id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)
        rows = self._conn.execute('select id, md5, page, title, content, bodyurl, texttitle, textcreator, created, modified, creator, annotates, color, local, mimetype, uuid, annotationurl from annotations where md5=? order by page', [self._filehash])
        for row in rows:
            self._annotations.append(AnnoBookmark(row))
            _logger.debug('picked %s', self._annotations[-1].get_note_body())
            _logger.debug('row content %s', row[4])




    def get_annotations_for_page(self, page):
        annotations = []
        for annotation in self._annotations:
            if annotation.belongstopage(page):
                annotations.append(annotation)
        return annotations
  


    def _resync_annotation_cache(self):
        # To be called when a new bookmark has been added/removed
        self._annotations = []
        self._populate_annotations()



    def get_pages_and_id_to_ann_map(self):
        pages = {}
        id_ann_map = {}
        if len(self._annotations) == 0:
            self._populate_annotations()
        for a in self._annotations:
            id_ann_map[a.id] = a
            if a.page in pages.keys():
                pages[a.page].append(a.id)
            else:
                pages[a.page] = [a.id]
                
        return pages, id_ann_map




    def get_prev_annotation(self, page):
        pages, id_ann_map = self.get_pages_and_id_to_ann_map()
        pages_with_annotations = sorted(pages.keys())
        if not pages_with_annotations == None:
            if self.current_annotation == None: 
                if not page in pages_with_annotations:
                    prevpages = [p for p in pages_with_annotations if p <= page]
                    if len(prevpages) > 0:
                        page = prevpages[-1]
                    else:
                        if len(pages_with_annotations) > 0:
                            page = pages_with_annotations[-1]
                if page in pages.keys():
                    self.current_annotation = id_ann_map[pages[page][0]]
            if not self.current_annotation == None: 
                t = pages[self.current_annotation.page]
                tind = t.index(self.current_annotation.id)
                if tind > 0: #prev annotation on the same page
                    self.current_annotation = id_ann_map[t[tind - 1]]
                else:    
                    self.current_annotation = id_ann_map[pages[pages_with_annotations[( pages_with_annotations.index(self.current_annotation.page) - 1 ) % len(pages_with_annotations)]][-1]]
                return self.current_annotation
        return None




    def get_next_annotation(self, page):
        pages, id_ann_map = self.get_pages_and_id_to_ann_map()
        pages_with_annotations = sorted(pages.keys())
        if not pages_with_annotations == None:
            if self.current_annotation == None: 
                if not page in pages_with_annotations:
                    nextpages = [p for p in pages_with_annotations if p >= page]
                    if len(nextpages) > 0:
                        page = nextpages[0]
                    else:
                        if len(pages_with_annotations) > 0:
                            page = pages_with_annotations[0]
                if page in pages.keys(): 
                    self.current_annotation = id_ann_map[pages[page][0]]
            if not self.current_annotation == None: 
                t = pages[self.current_annotation.page]
                tind = t.index(self.current_annotation.id)
                if tind < len(t) - 1: #next annotation on the same page
                    self.current_annotation = id_ann_map[t[tind + 1]]
                else:    
                    self.current_annotation = id_ann_map[pages[pages_with_annotations[( pages_with_annotations.index(self.current_annotation.page) + 1 ) % len(pages_with_annotations)]][0]]
                return self.current_annotation
        return None


                          


    def get_prev_annotation_for_page(self, page, wrap = True):
        if not len(self._annotations):
            return None
        
        if page <= self._annotations[0].page and wrap:
            return self._annotations[-1]
        else:
            for i in range(page-1, -1, -1):
                for annotation in self._annotations:
                    if annotation.belongstopage(i):
                        return annotation
                
        return None 



    def get_next_annotation_for_page(self, page, wrap = True):
        if not len(self._annotations):
            return None

        if page >= self._annotations[-1].page and wrap:
            return self._annotations[0]
        else:
            for i in range(page+1, self._annotations[-1].page + 1):
                for annotation in self._annotations:
                    if annotation.belongstopage(i):
                        return annotation

        return None    



    def get_node_data(self, domnode):
        if domnode != None:
            if domnode.firstChild != None:
              return domnode.firstChild.data
        return ''    



    def get_node_attribute(self, domnode, attributestr):
        if ( domnode != None ) and ( attributestr in domnode.attributes.keys() ):
            return domnode.attributes[attributestr].value
        return ''    




    def parse_annotations(self, json):
        annoarr = simplejson.loads(json)
        #annoarr = cjson.decode(json)
        remote_annotations = []
        #(id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)
        for a in annoarr:
            t = (a['id'], a['md5'], a['page'], a['title'], a['content'], a['bodyurl'], a['texttitle'], a['textcreator'], a['created'], a['modified'], a['creator'], a['annotates'], a['color'], a['local'], a['mimetype'], a['uuid'], a['annotationurl'])
            remote_annotations.append(AnnoBookmark(t))

        return remote_annotations




    def get_etext_metadata(self):    
        url_re  = re.compile('Link:\s+(http.*)')
        count   = 0
        url     = ""
        (results,count) = datastore.find({'mime_type' : ['application/epub+zip', 'application/pdf', mime.GENERIC_TYPE_TEXT]}, ['mime_type', 'checksum', 'description', 'title', 'author', 'publisher'])
        if count > 0:
            for r in results:
                m = r.get_metadata()
                if m['checksum'] == self._filehash:
                    if 'title' in m.keys():
                        self._texttitle = m['title']
                    if 'author' in m.keys():    
                        self._textcreator = m['author']
                    if 'url' in m.keys():    
                        url = m['url']
                        if len(url) == 0:
                            if len(m['description']) > 0:
                                t = url_re.search(m['description'])
                                if t:
                                    url = t.groups()[0].strip()
                        
                    self._annotates = url
                    _logger.debug('found url %s - self._annotates' % self._annotates)
                    _logger.debug('author: %s' % self._textcreator)
                    _logger.debug('title: %s' % self._texttitle)




    def insert_annotation_db_record(self, annotation):
        #(id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)
        t = (None, annotation.get_filehash(), annotation.get_page(), annotation.get_note_title(), annotation.get_note_body(), annotation.get_bodyurl(), annotation.get_texttitle(), annotation.get_textcreator(), annotation.get_created(), annotation.get_modified(), annotation.get_creator(), annotation.get_annotates(), annotation.get_color().to_string(), annotation.is_local(), annotation.get_mimetype(), annotation.get_uuid(), annotation.get_annotationurl())
        self._conn.execute('insert into annotations values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', t)
        self._conn.commit()
        row = self._conn.execute('select id from annotations order by id desc limit 1')
        r = row.fetchone() 
        tid = int( r[0] )
        annotation.set_id( tid )
        self.current_annotation = annotation

    
    def update_annotation_db_record(self, annotation):
        #if a user changes a annotation, it becomes her own
        if self._userid == '':
            client = gconf.client_get_default()
            user = client.get_string("/desktop/sugar/user/nick")
            self._userid = self.get_userid_for_username( self.get_user_string( user ) )
        annotation.set_creator( self._userid )
        annotation.make_new_uuid()
        #(id INTEGER PRIMARY KEY, md5, page, title, content, bodyurl, texttitle, textcreator, created TIMESTAMP, modified TIMESTAMP, creator, annotates, color, local, mimetype, uuid, annotationurl)
        t = (annotation.get_filehash(), annotation.get_page(), annotation.get_note_title(), annotation.get_note_body(), annotation.get_bodyurl(), annotation.get_texttitle(),  annotation.get_textcreator(), annotation.get_created(), annotation.get_modified(), self._userid, annotation.get_annotates(), annotation.get_color().to_string(), annotation.is_local(), annotation.get_mimetype(), annotation.get_uuid(), annotation.get_annotationurl(), annotation.get_id())
        self._conn.execute('update annotations set md5=?,  page=?,  title=?,  content=?,  bodyurl=?, texttitle=?, textcreator=?, created=?,  modified=?,  creator=?,  annotates=?, color=?,  local=?,  mimetype=?,  uuid=?,  annotationurl=? where id=?', t)
        self._conn.commit()
        self.current_annotation = annotation


    def makeDateTimeFromTimeStamp(self, tstamp):
        return time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(tstamp))

    
    def makeTimeStampFromDateTimeString(self, datetimestr):
        return time.mktime(time.strptime(datetimestr, "%Y-%m-%d %H:%M:%S"))


    def download_annotations(self):
        url = self._annotationserver
        annotations = []
        annojson = ""
        deleted_annotations_arr = self._conn.execute('select uuid from deleted_annotations')
        deleted_annotations = [ r[0] for r in deleted_annotations_arr]
        values = {'checksum' : self._filehash}
        _logger.debug('download annotations -- annotates is: %s ' % self._annotates)
        try:
            data = urllib.urlencode(values)          
            req = urllib2.Request(url, data)
            response = urllib2.urlopen(req)
            annojson = response.read() 
        except Exception, detail: 
            _logger.debug("readdb: failure at initial sync request f. annotations; detail: %s ", detail) 

        _logger.debug('annojson is: %s', str(annojson))
        if (annojson != None) and (len(annojson) > 0):    
            anno_arr = self.parse_annotations(annojson)  
            _logger.debug('length anno_arr %d', len(anno_arr))
            remote_uuids = []
            if len(anno_arr) > 0:
                remote_uuids = [a.get_uuid() for a in anno_arr]
                _logger.debug('remote_uuids %s', remote_uuids)
                #check the modified timestamps
                localuuids = [la.get_uuid() for la in self._annotations]
                self.remotecreators = []
                self.remotecolors = {}
                for a in anno_arr:
                    uuid = a.get_uuid()
                    if not uuid in deleted_annotations:
                        if uuid in localuuids:
                            _logger.debug('uuid exists locally')
                            ind = localuuids.index(uuid)
                            rmodifiedtstamp = a.get_modified()
                            _logger.debug(str('timestamps are remote: %d, local %d' % (rmodifiedtstamp, self._annotations[ind].get_modified())))
                            if self._annotations[ind].get_modified() < rmodifiedtstamp - self.modifiedtolerance:
                                _logger.debug('remote annotation is more recent than local annotation')
                                #take over the content
                                self._annotations[ind].set_note_title(a.get_note_title())
                                self._annotations[ind].set_note_body(a.get_note_body())
                                self._annotations[ind].set_modified(rmodifiedtstamp) 
                                self.update_annotation_db_record(a)
                                _logger.debug(str('after update: timestamps are remote: %d, local %d' % (rmodifiedtstamp, self._annotations[ind].get_modified())))
                            else:
                                if self._annotations[ind].get_creator() == self._creator:
                                    _logger.debug(str('remote annotation is outdated, sending %s' % self._annotations[ind]))
                                    self.send_annotation_to_server(self._annotations[ind]) 
                        else:  
                            remotecreator = a.get_creator()
                            if not remotecreator in self.remotecreators:
                                self.remotecreators.append(remotecreator)
                                self.remotecolors[remotecreator] = XoColor()
                                a.color = self.remotecolors[remotecreator]
                            self.insert_annotation_db_record(a)
                            self._annotations.append(a)
                            self._sidebar.update_for_page(a.page)



    def get_user_string( self, user ):
        m  = hashlib.md5()
        #m.update( str( "%s%d" % ( user, random.randint( 0, 100000000 ) ) ) )
        m.update( str( "%s" % ( user ) ) )
        return m.hexdigest()



    def sync_annotations(self):
        url         = self._annotationserver
        annotations = []
        annojson    = None
        _logger.debug("contacting annotationserver %s", url)
        #if self._annotates == "":
        #    self._annotates = self._texttitle
        #check if there are annotations to be deleted:
        if len(self._to_delete) > 0:
            for delete_anid in self._to_delete:
                if len(self._annotates) > 0:
                    values = {'w3c_hasTarget' : self._annotates, 'delete_anid': delete_anid }
                else:
                    values = {'checksum' : self._filehash, 'delete_anid': delete_anid }
                try:
                    data = urllib.urlencode(values)          
                    req = urllib2.Request(url, data)
                    response = urllib2.urlopen(req)
                    annojson = response.read() 
                    self._to_delete.remove(delete_anid)    
                    _logger.debug("\nafter delete, json is: %s\n\n" % annojson)
                except Exception, detail: 
                    _logger.debug("readdb: failure at request f. deleting annotations; detail: %s ", detail)
        else:
            #get annotations from server
            client = gconf.client_get_default()
            user = client.get_string("/desktop/sugar/user/nick")
            if self._userid == '':
                self._userid = self.get_userid_for_username( self.get_user_string( user ) )
            self._creator = self._userid 
            if len(self._annotates) > 0:
                values = {'w3c_hasTarget' : self._annotates }
            else:
                values = {'checksum' : self._filehash }

            _logger.debug('sync annotations -- annotates is: %s ' % self._annotates)
            try:
                data        = urllib.urlencode(values)          
                req         = urllib2.Request(url, data)
                response    = urllib2.urlopen(req)
                annojson    = response.read() 
                _logger.debug('downloaded annotations -- annojson is: %s ' % annojson)
            except Exception, detail: 
                _logger.debug("readdb: failure at initial sync request f. annotations; detail: %s ", detail) 
        if ( not annojson == None ) and ( len( annojson ) > 0 ):    
            anno_arr = self.parse_annotations(annojson)  
            _logger.debug('length anno_arr %d', len(anno_arr))
            remote_uuids = []
            if len(anno_arr) > 0:
                localuuids = [la.get_uuid() for la in self._annotations]
                remote_uuids = [a.get_uuid() for a in anno_arr]
                _logger.debug('remote_uuids %s', remote_uuids)
                #check the modified timestamps
                for a in anno_arr:
                    uuid = a.get_uuid()
                    if uuid in localuuids:
                        _logger.debug('uuid exists locally')
                        ind = localuuids.index(uuid)
                        rmodifiedtstamp = a.get_modified()
                        _logger.debug(str('timestamps are remote: %d, local %d' % (rmodifiedtstamp, self._annotations[ind].get_modified())))
                        if self._annotations[ind].get_modified() < rmodifiedtstamp - self.modifiedtolerance:
                            _logger.debug('remote annotation is more recent than local annotation')
                            #take over the content
                            self._annotations[ind].set_note_title(a.get_note_title())
                            self._annotations[ind].set_note_body(a.get_note_body())
                            self._annotations[ind].set_modified(rmodifiedtstamp) 
                            _logger.debug(str('after update: timestamps are remote: %d, local %d' % (rmodifiedtstamp, self._annotations[ind].get_modified())))
                            self.update_annotation_db_record(a)
                        else:
                            if self._annotations[ind].get_creator() == self._userid:
                                _logger.debug(str('remote annotation is outdated, sending %s' % self._annotations[ind]))
                                self.send_annotation_to_server(self._annotations[ind])

            if (len(self._annotations) > 0):
                #send annotations if necessary 
                for annotation in self._annotations:
                    if ( not annotation.get_uuid() in remote_uuids ) and ( len( annotation.get_creator() ) > 0 ) and ( annotation.get_creator() == self._userid ): 
                        self.send_annotation_to_server(annotation)



    def send_annotation_to_server(self, annotation):
        url = self._annotationserver
        annojson = annotation.get_json()
        _logger.debug('it is a new or updated annotation, trying to send it to server, json: %s', annojson)
        try:
            req = urllib2.Request(url, annojson, {'Content-Type': 'application/json', "Accept": "application/json"} )
            #req = urllib2.Request(url, annojson, {"Content-type": "application/x-www-form-urlencoded"y} )
            response = urllib2.urlopen(req)       
            re_json = response.read()
            json_arr = simplejson.loads(re_json)
            _logger.debug('json response from the server: %s', re_json )
            
            annourl = json_arr['annotationurl']
            _logger.debug('got this annourl back from server: %s', annourl )
            if annourl != None:
                annotation.set_annotationurl( annourl )
            
            bodyurl = json_arr['bodyurl']
            _logger.debug('got this bodyurl back from server: %s', bodyurl)
            if bodyurl != None:
                annotation.set_bodyurl(bodyurl)
            
            self.update_annotation_db_record( annotation )
        except Exception, detail:
          _logger.debug("readdb: sending annotation failed: %s ", detail)


