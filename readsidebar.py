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

import logging
import time

import gtk

from sugar.graphics import style
from sugar.graphics.icon import Icon
from sugar.graphics.xocolor import XoColor
from sugar import profile
from sugar.util import timestamp_to_elapsed_string

from annobookmark import AnnoBookmark, Bookmark
from readdb import AnnotationManager
from readdialog import BookmarkAddDialog, BookmarkEditDialog, AnnotationAddDialog, AnnotationEditDialog
from annoicon import AnnoIcon


from gettext import gettext as _

_logger = logging.getLogger('anno-activity')

#TODO: Add support for multiple bookmarks in a single page (required when sharing)

class Sidebar(gtk.EventBox):
    def __init__(self):
        gtk.EventBox.__init__(self)
        self.set_size_request(22, -1)
        # Take care of the background first
        white = gtk.gdk.color_parse("white")
        self.modify_bg(gtk.STATE_NORMAL, white)

        self._box = gtk.VButtonBox()
        self._box.set_layout(gtk.BUTTONBOX_CENTER)
        self.add(self._box)

        self._box.show()
        self.show()
        
        self._bookmark_icon = None
        self._annotation_icon = None
        self._annotation_icons = []
        self._annotation_event_ids = []
        self._annotation_icon_query_tooltip_cb_ids = []
        self._bookmark_manager = None
        self._annotation_manager = None
        self._is_showing_local_annotation = False

        #self.add_events(gtk.gdk.BUTTON_PRESS_MASK)



    def is_showing_local_annotation(self):
        return self._is_showing_local_annotation
   



    def __event_cb(self, widget, event, annotation):
        if event.type == gtk.gdk.BUTTON_PRESS and \
                    self._annotation_icons != []:

            annotation_title = annotation.get_note_title()
            annotation_content = annotation.get_note_body()
            annotation_id = annotation.get_id()
    
            dialog = AnnotationEditDialog(parent_xid = self.get_toplevel().window.xid, \
                dialog_title = _("Edit notes for annotation: "), \
                annotation_id = annotation_id, \
                annotation_title = annotation_title, \
                annotation_content = annotation_content, page = annotation.page, \
                sidebarinstance = self)
            dialog.show_all()
        
        return False


        
    def _clear_annotations(self):
        if len(self._annotation_icons) > 0:
            for i in range(len(self._annotation_icons)):
              annotation_icon = self._annotation_icons[i]          
              annotation_icon._disconnect()
              annotation_icon.hide() 
              annotation_icon.destroy()
              self._annotation_icons[i] = None
            
        self._annotation_icons = []
        self._annotation_icon_query_tooltip_cb_ids = []
        self._annotation_event_ids = []
        self._is_showing_local_annotation = False



    def set_annotationmanager(self, annotation_manager):
        self._annotation_manager = annotation_manager
       

    def get_annotationmanager(self):
        return (self._annotation_manager)
    

    def update_for_page(self, page): 
        self._clear_annotations()
        annotations = self._annotation_manager.get_annotations_for_page(page)
        for annotation in annotations:
            self._add_annotation_icon(annotation)

    
    def sync_annotations(self):
        self._annotation_manager.sync_annotations()


    def download_annotations(self):
        self._annotation_manager.download_annotations()


    def add_annotation(self, page):
        annotation_title = (_("%s's annotation") % profile.get_nick_name())
        annotation_content = (_("Annotation for page %d") % (page + 1))
        dialog = AnnotationAddDialog(parent_xid = self.get_toplevel().window.xid, \
            dialog_title = _("Add notes for annotation: "), \
            annotation_id = 0, \
            annotation_title = annotation_title, \
            annotation_content = annotation_content, page = page, \
            sidebarinstance = self)
        dialog.show_all()

    def _real_add_annotation(self, page, content):
        self._annotation_manager.add_annotation(page, unicode(content))
        self.update_for_page(page)



    def _real_edit_annotation(self, page, content, annotation_id):
        self._annotation_manager.edit_annotation(page, unicode(content), annotation_id)
        self.update_for_page(page)


    def _real_delete_annotation(self, page, annotation_id):
        self.del_annotation(page, annotation_id)


    def del_annotation(self, page, annotation_id):
        _logger.debug('annotation %d scheduled for deletion' % annotation_id)
        self._annotation_manager.del_annotation(annotation_id)
        self.update_for_page(page)
    


    def _add_annotation_icon(self, annotation):
        #xocolor = XoColor(annotation.color)
        xocolor = annotation.color
        annotation_icon = AnnoIcon(icon_name = 'emblem-favorite', \
            xo_color = xocolor, annotation=annotation, \
            event_cb=self.__event_cb)

        self._box.pack_start(annotation_icon ,expand=False,fill=False)
        annotation_icon.show_all()
        self._annotation_icons.append(annotation_icon)

        if annotation.is_local():
            self._is_showing_local_annotation = True

    """
    def __annotation_icon_query_tooltip_cb(self, widget, x, y, keyboard_mode, tip, annotation):
        tooltip_header = annotation.get_note_title()
        tooltip_body = annotation.get_note_body()
        #TRANS: This goes like annotation added by User 5 days ago (the elapsed string gets translated
        #TRANS: automatically)
        #tooltip_footer = (_('annotation added by %(user)s %(time)s') \
        #        % {'user': annotation.creator, 'time': timestamp_to_elapsed_string(float(annotation.created))})

        vbox = gtk.VBox()

        l = gtk.Label('<big>%s</big>' % tooltip_header)
        l.set_use_markup(True)
        l.set_width_chars(40)
        l.set_line_wrap(True)
        vbox.pack_start(l, expand = False, fill = False)
        l.show()

        l = gtk.Label('%s' % tooltip_body)
        l.set_use_markup(True)
        l.set_alignment(0, 0)
        l.set_padding(2, 6)
        l.set_width_chars(40)
        l.set_line_wrap(True)
        l.set_justify(gtk.JUSTIFY_FILL)
        vbox.pack_start(l, expand = True, fill = True)
        l.show()

        #l = gtk.Label('<small><i>%s</i></small>' % tooltip_footer)
        #l.set_use_markup(True)
        #l.set_width_chars(40)
        #l.set_line_wrap(True)
        #vbox.pack_start(l, expand = False, fill = False)
        #l.show()

        tip.set_custom(vbox)

        return True
    """        
           
