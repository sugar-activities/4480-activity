# Copyright (C) 2007, Red Hat, Inc.
# Copyright (C) 2007 Collabora Ltd. <http://www.collabora.co.uk/>
# Copyright 2008 One Laptop Per Child
# Copyright 2009 Simon Schampijer
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
import os
import time
from gettext import gettext as _
import re
import md5

import dbus
import gobject
import gtk
import pango
import telepathy

from sugar.activity import activity
from sugar.graphics.toolbutton import ToolButton
from sugar.graphics.toolbarbox import ToolbarBox
from sugar.graphics.toolbarbox import ToolbarButton
from sugar.graphics.toolcombobox import ToolComboBox
from sugar.graphics.toggletoolbutton import ToggleToolButton
from sugar.graphics.menuitem import MenuItem
from sugar.activity.widgets import ActivityToolbarButton
from sugar.activity.widgets import StopButton
from sugar import network
from sugar import mime

#from jarabe.journal import journalactivity
from sugar.datastore import datastore
from sugar.graphics.objectchooser import ObjectChooser

from readtoolbar import EditToolbar
from readtoolbar import ViewToolbar
from readtoolbar import SpeechToolbar
from readsidebar import Sidebar
from readtopbar import TopBar

from readdb import AnnotationManager
import epubadapter
import evinceadapter
import textadapter
import speech

#
#_EPUB_SUPPORT = True
#try:
#    import epubadapter
#except ImportError, e:
#    _EPUB_SUPPORT = False
#    logging.warning('Epub support disabled because: %s' % e)

_HARDWARE_MANAGER_INTERFACE = 'org.laptop.HardwareManager'
_HARDWARE_MANAGER_SERVICE = 'org.laptop.HardwareManager'
_HARDWARE_MANAGER_OBJECT_PATH = '/org/laptop/HardwareManager'

_TOOLBAR_READ = 2

_logger = logging.getLogger('anno-activity')

def _get_screen_dpi():
    xft_dpi = gtk.settings_get_default().get_property('gtk-xft-dpi')
    _logger.debug('Setting dpi to %f', float(xft_dpi / 1024))
    return float(xft_dpi / 1024)

def get_md5(filename): #FIXME: Should be moved somewhere else
    filename = filename.replace('file://', '') #XXX: hack 
    fh = open(filename)
    digest = md5.new()
    while 1:
        buf = fh.read(4096)
        if buf == "":
            break
        digest.update(buf)
    fh.close()
    return digest.hexdigest()

class AnnoHTTPRequestHandler(network.ChunkedGlibHTTPRequestHandler):
    """HTTP Request Handler for transferring document while collaborating.

    RequestHandler class that integrates with Glib mainloop. It writes
    the specified file to the client in chunks, returning control to the
    mainloop between chunks.

    """
    def translate_path(self, path):
        """Return the filepath to the shared document."""
        return self.server.filepath


class AnnoHTTPServer(network.GlibTCPServer):
    """HTTP Server for transferring document while collaborating."""
    def __init__(self, server_address, filepath):
        """Set up the GlibTCPServer with the AnnoHTTPRequestHandler.

        filepath -- path to shared document to be served.
        """
        self.filepath = filepath
        network.GlibTCPServer.__init__(self, server_address,
                                       AnnoHTTPRequestHandler)


class AnnoURLDownloader(network.GlibURLDownloader):
    """URLDownloader that provides content-length and content-type."""

    def get_content_length(self):
        """Return the content-length of the download."""
        if self._info is not None:
            return int(self._info.headers.get('Content-Length'))

    def get_content_type(self):
        """Return the content-type of the download."""
        if self._info is not None:
            return self._info.headers.get('Content-type')
        return None


READ_STREAM_SERVICE = 'anno-activity-http'

class AnnoActivity(activity.Activity):
    """The Anno sugar activity."""
    def __init__(self, handle):
        activity.Activity.__init__(self, handle)

        #self._epub = False
        self._document = None
        self._fileserver = None
        self._object_id = handle.object_id
        self._url = ''
        self._title     = ''
        self._author    = '' 

        self._model = None
        self._toc_model = None

        self._mimetype = None

        self.connect('key-press-event', self._key_press_event_cb)
        self.connect('key-release-event', self._key_release_event_cb)
        #self.connect('window-state-event', self._window_state_event_cb)

        _logger.debug('Starting Anno...')
        
        self._view = None
        self.dpi = _get_screen_dpi()

        self._sidebar = Sidebar()
        self._sidebar.show()

        toolbar_box = ToolbarBox()

        activity_button = ActivityToolbarButton(self)
        toolbar_box.toolbar.insert(activity_button, 0)
        activity_button.show()

        self._edit_toolbar = EditToolbar()
        self._edit_toolbar.undo.props.visible = False
        self._edit_toolbar.redo.props.visible = False
        self._edit_toolbar.separator.props.visible = False
        self._edit_toolbar.copy.set_sensitive(False)
        self._edit_toolbar.copy.connect('clicked', self._edit_toolbar_copy_cb)
        self._edit_toolbar.paste.props.visible = False

        edit_toolbar_button = ToolbarButton(
                page=self._edit_toolbar,
                icon_name='toolbar-edit')
        self._edit_toolbar.show()
        toolbar_box.toolbar.insert(edit_toolbar_button, -1)
        edit_toolbar_button.show()

        self._view_toolbar = ViewToolbar()
        self._view_toolbar.connect('go-fullscreen',
                self.__view_toolbar_go_fullscreen_cb)
        view_toolbar_button = ToolbarButton(
                page=self._view_toolbar,
                icon_name='toolbar-view')
        self._view_toolbar.show()
        toolbar_box.toolbar.insert(view_toolbar_button, -1)
        view_toolbar_button.show()

        self._back_button = self._create_back_button()
        toolbar_box.toolbar.insert(self._back_button, -1)
        self._back_button.show()

        self._forward_button = self._create_forward_button()
        toolbar_box.toolbar.insert(self._forward_button, -1)
        self._forward_button.show()

        num_page_item = gtk.ToolItem()
        self._num_page_entry = self._create_search()
        num_page_item.add(self._num_page_entry)
        self._num_page_entry.show()
        toolbar_box.toolbar.insert(num_page_item, -1)
        num_page_item.show()

        total_page_item = gtk.ToolItem()
        self._total_page_label = self._create_total_page_label()
        total_page_item.add(self._total_page_label)
        self._total_page_label.show()
        toolbar_box.toolbar.insert(total_page_item, -1)
        total_page_item.show()

        spacer = gtk.SeparatorToolItem()
        spacer.props.draw = False
        toolbar_box.toolbar.insert(spacer, -1)
        spacer.show()

        navigator_toolbar = gtk.Toolbar()
        #navigator_item = gtk.ToolItem()
        self._navigator = self._create_navigator()
        #navigator_item.add(self._navigator)
        combotool = ToolComboBox(self._navigator) 
        navigator_toolbar.insert(combotool, -1)

        self._navigator.show()
        combotool.show()
        self._navigator_toolbar_button = ToolbarButton(page=navigator_toolbar,
                                                 icon_name='view-list')
        navigator_toolbar.show()
        toolbar_box.toolbar.insert(self._navigator_toolbar_button, -1)
        #navigator_toolbar_button.show()

        spacer = gtk.SeparatorToolItem()
        spacer.props.draw = False
        toolbar_box.toolbar.insert(spacer, -1)
        spacer.show()
        
        annotator_item = gtk.ToolItem()
        self._annotator = self._create_annotator()
        self._annotator_toggle_handler_id = self._annotator.connect( \
                'toggled', self.__annotator_toggled_cb)
        annotator_item.add(self._annotator)
        self._annotator.show()
        toolbar_box.toolbar.insert(annotator_item, -1)
        annotator_item.show()
       
        annotator_syncer_item = gtk.ToolItem()
        self._annotator_syncer = self._create_annotator_syncer()
        self._annotator_syncer_toggle_handler_id = self._annotator_syncer.connect( \
                'toggled', self.__annotator_syncer_toggled_cb)
        annotator_syncer_item.add(self._annotator_syncer)
        self._annotator_syncer.show()
        toolbar_box.toolbar.insert(annotator_syncer_item, -1)
        annotator_syncer_item.show()


        annotator_downloader_item = gtk.ToolItem()
        self._annotator_downloader = self._create_annotator_downloader()
        self._annotator_downloader_toggle_handler_id = self._annotator_downloader.connect( \
                'toggled', self.__annotator_downloader_toggled_cb)
        annotator_downloader_item.add(self._annotator_downloader)
        self._annotator_downloader.show()
        toolbar_box.toolbar.insert(annotator_downloader_item, -1)
        annotator_downloader_item.show()



        self._highlight_item = gtk.ToolItem()
        self._highlight = ToggleToolButton('format-text-underline')
        self._highlight.set_tooltip(_('Highlight'))
        self._highlight.props.sensitive = False
        self._highlight_id = self._highlight.connect('clicked', \
                self.__highlight_cb)
        self._highlight_item.add(self._highlight)
        toolbar_box.toolbar.insert(self._highlight_item, -1)
        self._highlight_item.show_all()

        self.speech_toolbar = SpeechToolbar(self)
        self.speech_toolbar_button = ToolbarButton(page=self.speech_toolbar,
                    icon_name='speak')
        toolbar_box.toolbar.insert(self.speech_toolbar_button, -1)


        stop_button = StopButton(self)
        #stop_button.props.accelerator = '<Ctrl><Shift>Q'
        toolbar_box.toolbar.insert(stop_button, -1)
        stop_button.show()

        self.set_toolbar_box(toolbar_box)
        toolbar_box.show()

        self._vbox = gtk.VBox()
        self._vbox.show()

        self._topbar = TopBar()
        self._vbox.pack_start(self._topbar, expand = False, fill = False)

        self._hbox = gtk.HBox()
        self._hbox.show()
        self._hbox.pack_start(self._sidebar, expand=False, fill=False)

        self._vbox.pack_start(self._hbox, expand = True, fill = True)
        self.set_canvas(self._vbox)

        # Set up for idle suspend
        self._idle_timer = 0
        self._service = None

        # start with sleep off
        self._sleep_inhibit = True

        self.unused_download_tubes = set()
        self._want_document = True
        self._download_content_length = 0
        self._download_content_type = None
        # Status of temp file used for write_file:
        self._tempfile = None
        self._close_requested = False

        #self._journal = journalactivity.get_journal()


        fname = os.path.join('/etc', 'inhibit-ebook-sleep')
        if not os.path.exists(fname):
            try:
                bus = dbus.SystemBus()
                proxy = bus.get_object(_HARDWARE_MANAGER_SERVICE,
                                       _HARDWARE_MANAGER_OBJECT_PATH)
                self._service = dbus.Interface(proxy,
                                               _HARDWARE_MANAGER_INTERFACE)
                self._scrolled.props.vadjustment.connect("value-changed",
                                                   self._user_action_cb)
                self._scrolled.props.hadjustment.connect("value-changed",
                                                   self._user_action_cb)
                self.connect("focus-in-event", self._focus_in_event_cb)
                self.connect("focus-out-event", self._focus_out_event_cb)
                self.connect("notify::active", self._now_active_cb)

                _logger.debug('Suspend on idle enabled')
            except dbus.DBusException, e:
                _logger.info(
                    'Hardware manager service not found, no idle suspend.')
        else:
            _logger.debug('Suspend on idle disabled')

        self.connect("shared", self._shared_cb)

        h = hash(self._activity_id)
        self.port = 1024 + (h % 64511)
        

        if handle.uri:
            self._load_document(handle.uri)

        if self.shared_activity:
            # We're joining
            if self.get_shared():
                # Already joined for some reason, just get the document
                self._joined_cb(self)
            else:
                # Wait for a successful join before trying to get the document
                self.connect("joined", self._joined_cb)
        elif self._object_id is None:
            # Not joining, not resuming
            self._show_journal_object_picker()
        # uncomment this and adjust the path for easier testing
        #else:
        #    self._load_document('file:///home/smcv/tmp/test.pdf')


    def fullscreen(self):
        self._topbar.show_all()
        activity.Activity.fullscreen(self)


    def unfullscreen(self):
        self._topbar.hide()
        activity.Activity.unfullscreen(self)






    def _create_back_button(self):
        back = ToolButton('go-previous')
        back.set_tooltip(_('Back'))
        back.props.sensitive = False
        palette = back.get_palette()
        previous_page = MenuItem(text_label= _("Previous page"))
        palette.menu.append(previous_page) 
        previous_page.show_all()        
        previous_annotation = MenuItem(text_label= _("Previous annotation"))
        palette.menu.append(previous_annotation) 
        previous_annotation.show_all()
        back.connect('clicked', self.__go_back_cb)
        previous_page.connect('activate', self.__go_back_page_cb)
        previous_annotation.connect('activate', self.__prev_annotation_activate_cb)
        return back

    def _create_forward_button(self):
        forward = ToolButton('go-next')
        forward.set_tooltip(_('Forward'))
        forward.props.sensitive = False
        palette = forward.get_palette()
        next_page = MenuItem(text_label= _("Next page"))
        palette.menu.append(next_page) 
        next_page.show_all()        
        next_annotation = MenuItem(text_label= _("Next annotation"))
        palette.menu.append(next_annotation) 
        next_annotation.show_all()
        forward.connect('clicked', self.__go_forward_cb)
        next_page.connect('activate', self.__go_forward_page_cb)
        next_annotation.connect('activate', self.__next_annotation_activate_cb)
        return forward

    def _create_search(self):
        num_page_entry = gtk.Entry()
        num_page_entry.set_text('0')
        num_page_entry.set_alignment(1)
        num_page_entry.connect('insert-text',
                               self.__num_page_entry_insert_text_cb)
        num_page_entry.connect('activate',
                               self.__num_page_entry_activate_cb)
        num_page_entry.set_width_chars(4)
        return num_page_entry

    def _create_total_page_label(self):
        total_page_label = gtk.Label()

        label_attributes = pango.AttrList()
        label_attributes.insert(pango.AttrSize(14000, 0, -1))
        label_attributes.insert(pango.AttrForeground(65535, 65535, 
                                                     65535, 0, -1))
        total_page_label.set_attributes(label_attributes)

        total_page_label.set_text(' / 0')
        return total_page_label
    
    def _create_navigator(self):
        navigator = gtk.ComboBox()
        navigator.set_add_tearoffs(True)
        cell = gtk.CellRendererText()
        navigator.pack_start(cell, True)
        navigator.add_attribute(cell, 'text', 0)
        navigator.props.visible = False
        return navigator

    def _create_annotator(self):
        annotator = ToggleToolButton('emblem-favorite')
        annotator.set_tooltip(_('Add annotation'))
        return annotator
    
    def _create_annotator_syncer(self):
        syncer = ToggleToolButton('go-up')
        syncer.set_tooltip(_('Sync annotations'))
        return syncer
    
    def _create_annotator_downloader(self):
        downloader = ToggleToolButton('go-down')
        downloader.set_tooltip(_('Download annotations'))
        return downloader


    def __num_page_entry_insert_text_cb(self, entry, text, length, position):
        if not re.match('[0-9]', text):
            entry.emit_stop_by_name('insert-text')
            return True
        return False

    def __num_page_entry_activate_cb(self, entry):
        if entry.props.text:
            page = int(entry.props.text) - 1
        else:
            page = 0

        #if page >= self._view.get_pagecount():
        #    page = self._view.get_pagecount() - 1
        #elif page < 0:
        #    page = 0

        #self._model.props.page = page
        self._view.set_current_page(page) 
        entry.props.text = str(page + 1)
    
    def __go_back_cb(self, button):
        self._view.scroll(gtk.SCROLL_PAGE_BACKWARD, False)

    def __go_forward_cb(self, button):
        self._view.scroll(gtk.SCROLL_PAGE_FORWARD, False)

    def __go_back_page_cb(self, button):
        self._view.previous_page()
    
    def __go_forward_page_cb(self, button):
        self._view.next_page()

    def __highlight_cb(self, button):
        tuples_list = self._annotationmanager.get_highlights(
                self._view.get_current_page())
        selection_tuple = self._view.get_selection_bounds()
        cursor_position = self._view.get_cursor_position()

        old_highlight_found = None
        for compare_tuple in tuples_list:
            if selection_tuple:
                if selection_tuple[0] >= compare_tuple[0] and \
                        selection_tuple[1] <= compare_tuple[1]:
                    old_highlight_found = compare_tuple
                    break
            if cursor_position >= compare_tuple[0] and \
               cursor_position <= compare_tuple[1]:
                old_highlight_found = compare_tuple
                break

        if old_highlight_found == None:
            self._annotationmanager.add_highlight(
                    self._view.get_current_page(), selection_tuple)
        else:
            self._annotationmanager.del_highlight(
                    self._view.get_current_page(), old_highlight_found)

        self._view.show_highlights(self._annotationmanager.get_highlights(
                self._view.get_current_page()))




    def __prev_annotation_activate_cb(self, menuitem):
        page = self._view.get_current_page()
        annomanager = self._sidebar.get_annotationmanager()
        
        prev_anno = annomanager.get_prev_annotation(page)
        if prev_anno is not None:
            _logger.debug('prev annotation page is %d' % prev_anno.page)
            self._view.set_current_page(prev_anno.page)


    def __next_annotation_activate_cb(self, menuitem):
        page = self._view.get_current_page()
        annomanager = self._sidebar.get_annotationmanager()
        
        next_anno= annomanager.get_next_annotation(page)
        
        if next_anno is not None:
            _logger.debug('next annotation page is %d' % next_anno.page)
            self._view.set_current_page(next_anno.page)

    def __bookmarker_toggled_cb(self, button):
        page = self._view.get_current_page()
        if self._bookmarker.props.active:
            self._sidebar.add_bookmark(page)
        else:
            self._sidebar.del_bookmark(page)    

    def __annotator_toggled_cb(self, button):
        page = self._view.get_current_page()
        if self._annotator.props.active:
            self._sidebar.add_annotation(page)

    def __annotator_syncer_toggled_cb(self, button):
        self._sidebar.sync_annotations()


    def __annotator_downloader_toggled_cb(self, button):
        self._sidebar.download_annotations()

    def __page_changed_cb(self, model, page_from, page_to):
        self._update_nav_buttons()
        if self._toc_model != None:
            self._toc_select_active_page()

        self._sidebar.update_for_page(self._view.get_current_page())
        self._annotator.handler_block(self._annotator_toggle_handler_id)
        self._annotator.props.active = self._sidebar.is_showing_local_annotation()
        self._annotator.handler_unblock(self._annotator_toggle_handler_id)
        tuples_list = self._annotationmanager.get_highlights(
                self._view.get_current_page())
        if self._view.can_highlight():
            self._view.show_highlights(tuples_list)



        
    def _update_nav_buttons(self):
        current_page = self._view.get_current_page()
        self._back_button.props.sensitive = current_page > 0
        self._forward_button.props.sensitive = \
            current_page < self._view.get_pagecount() - 1
        
        self._num_page_entry.props.text = str(current_page + 1)
        self._total_page_label.props.label = \
            ' / ' + str(self._view.get_pagecount())

    def _update_toc(self):
        if self._view.update_toc(self):
            self._navigator_changed_handler_id = \
                self._navigator.connect('changed', self.__navigator_changed_cb)

        
    def __navigator_changed_cb(self, combobox):
        iter = self._navigator.get_active_iter()

        link = self._toc_model.get(iter, 1)[0]
        self._view.handle_link(link)

    def _toc_select_active_page_foreach(self, model, path, iter, current_page):
        link = self._toc_model.get(iter, 1)[0]

        if not hasattr(link, 'get_page'):
            #FIXME: This needs to be implemented in epubadapter, not here
            filepath = self._view.get_current_file()
            if filepath.endswith(link):
                self._navigator.set_active_iter(iter)
                return True
        else:
            if current_page == link.get_page():
                self._navigator.set_active_iter(iter)
                return True

        return False

    def _toc_select_active_page(self):
        iter = self._navigator.get_active_iter()
        
        current_link = self._toc_model.get(iter, 1)[0]
        current_page = self._view.get_current_page()

        if not hasattr(current_link, 'get_page'):
            filepath = self._view.get_current_file()
            if filepath is None or filepath.endswith(current_link):
                return
        else:
            if current_link.get_page() == current_page:
                return

        self._navigator.handler_block(self._navigator_changed_handler_id)
        self._toc_model.foreach(self._toc_select_active_page_foreach, current_page)
        self._navigator.handler_unblock(self._navigator_changed_handler_id)

    def _show_journal_object_picker(self):
        """Show the journal object picker to load a document.

        This is for if Anno is launched without a document.
        """
        if not self._want_document:
            return
        chooser = ObjectChooser(_('Choose document'), self, 
                                gtk.DIALOG_MODAL | 
                                gtk.DIALOG_DESTROY_WITH_PARENT,
                                what_filter=mime.GENERIC_TYPE_TEXT)
        try:
            result = chooser.run()
            if result == gtk.RESPONSE_ACCEPT:
                logging.debug('ObjectChooser: %r' % 
                              chooser.get_selected_object())
                jobject = chooser.get_selected_object()
                if jobject and jobject.file_path:
                    self.read_file(jobject.file_path)
                    properties = jobject.metadata.get_dictionary().copy()
                    _logger.debug('\n\n\nthe metadata properties: %s' % str(properties))
                    pkeys = properties.keys()
                    if 'url' in pkeys:
                        self._url       = properties['url']
                    if 'title' in pkeys:
                        self._title     = properties['title']
                    if 'author' in pkeys:
                        self._author    = properties['author'] 
        finally:
            chooser.destroy()
            del chooser

    def _now_active_cb(self, widget, pspec):
        if self.props.active:
            # Now active, start initial suspend timeout
            if self._idle_timer > 0:
                gobject.source_remove(self._idle_timer)
            self._idle_timer = gobject.timeout_add_seconds(15, self._suspend_cb)
            self._sleep_inhibit = False
        else:
            # Now inactive
            self._sleep_inhibit = True

    def _focus_in_event_cb(self, widget, event):
        """Enable ebook mode idle sleep since Anno has focus."""
        self._sleep_inhibit = False
        self._user_action_cb(self)

    def _focus_out_event_cb(self, widget, event):
        """Disable ebook mode idle sleep since Anno lost focus."""
        self._sleep_inhibit = True

    def _user_action_cb(self, widget):
        """Set a timer for going back to ebook mode idle sleep."""
        if self._idle_timer > 0:
            gobject.source_remove(self._idle_timer)
        self._idle_timer = gobject.timeout_add_seconds(5, self._suspend_cb)

    def _suspend_cb(self):
        """Go into ebook mode idle sleep."""
        # If the machine has been idle for 5 seconds, suspend
        self._idle_timer = 0
        if not self._sleep_inhibit and not self.get_shared():
            self._service.set_kernel_suspend()
        return False

    def read_file(self, file_path):
        """Load a file from the datastore on activity start."""
        _logger.debug('AnnoActivity.read_file: %s', file_path)
        extension = os.path.splitext(file_path)[1]
        tempfile = os.path.join(self.get_activity_root(), 'instance',
                                'tmp%i%s' % (time.time(), extension))
        os.link(file_path, tempfile)
        self._tempfile = tempfile
        self._load_document('file://' + self._tempfile)

        # FIXME: This should obviously be fixed properly
        gobject.timeout_add_seconds(1, self.__view_toolbar_needs_update_size_cb,
            None)

    def write_file(self, file_path):
        """Write into datastore for Keep.
        
        The document is saved by hardlinking from the temporary file we
        keep around instead of "saving".

        The metadata is updated, including current page, view settings,
        search text.
        
        """
        if self._tempfile is None:
            # Workaround for closing Anno with no document loaded
            raise NotImplementedError

        try:
            self.metadata['Anno_current_page'] = \
                        str(self._model.props.page)
            self.metadata['Anno_zoom'] = str(self._view.get_current_page())
                
            self.metadata['url']    = self._url
            _logger.debug(str('set url to %s' % self._url))
            self.metadata['title']  = self._title
            self.metadata['author'] = self._author

            self._view.update_metadata(self)
            
            self.metadata['Anno_search'] = \
                    self._edit_toolbar._search_entry.props.text

        except Exception, e:
            _logger.error('write_file(): %s', e)

        self.metadata['Anno_search'] = \
                self._edit_toolbar._search_entry.props.text

        self.metadata['activity']   = self.get_bundle_id()

        os.link(self._tempfile, file_path)

        if self._close_requested:
            _logger.debug("Removing temp file %s because we will close",
                          self._tempfile)
            os.unlink(self._tempfile)
            self._tempfile = None

    def can_close(self):
        """Prepare to cleanup on closing.
        
        Called from self.close()
        """
        self._close_requested = True
        return True

    def _download_result_cb(self, getter, tempfile, suggested_name, tube_id):
        if self._download_content_type == 'text/html':
            # got an error page instead
            self._download_error_cb(getter, 'HTTP Error', tube_id)
            return

        del self.unused_download_tubes

        self._tempfile = tempfile
        file_path = os.path.join(self.get_activity_root(), 'instance',
                                    '%i' % time.time())
        _logger.debug("Saving file %s to datastore...", file_path)
        os.link(tempfile, file_path)
        self._jobject.file_path = file_path
        datastore.write(self._jobject, transfer_ownership=True)

        _logger.debug("Got document %s (%s) from tube %u",
                      tempfile, suggested_name, tube_id)
        self._load_document("file://%s" % tempfile)
        self.save()

    def _download_progress_cb(self, getter, bytes_downloaded, tube_id):
        # FIXME: Draw a progress bar
        if self._download_content_length > 0:
            _logger.debug("Downloaded %u of %u bytes from tube %u...",
                          bytes_downloaded, self._download_content_length, 
                          tube_id)
        else:
            _logger.debug("Downloaded %u bytes from tube %u...",
                          bytes_downloaded, tube_id)

    def _download_error_cb(self, getter, err, tube_id):
        _logger.debug("Error getting document from tube %u: %s",
                      tube_id, err)
        self._want_document = True
        self._download_content_length = 0
        self._download_content_type = None
        gobject.idle_add(self._get_document)

    def _download_document(self, tube_id, path):
        # FIXME: should ideally have the CM listen on a Unix socket
        # instead of IPv4 (might be more compatible with Rainbow)
        chan = self.shared_activity.telepathy_tubes_chan
        iface = chan[telepathy.CHANNEL_TYPE_TUBES]
        addr = iface.AcceptStreamTube(tube_id,
                telepathy.SOCKET_ADDRESS_TYPE_IPV4,
                telepathy.SOCKET_ACCESS_CONTROL_LOCALHOST, 0,
                utf8_strings=True)
        _logger.debug('Accepted stream tube: listening address is %r', addr)
        # SOCKET_ADDRESS_TYPE_IPV4 is defined to have addresses of type '(sq)'
        assert isinstance(addr, dbus.Struct)
        assert len(addr) == 2
        assert isinstance(addr[0], str)
        assert isinstance(addr[1], (int, long))
        assert addr[1] > 0 and addr[1] < 65536
        port = int(addr[1])

        getter = AnnoURLDownloader("http://%s:%d/document"
                                           % (addr[0], port))
        getter.connect("finished", self._download_result_cb, tube_id)
        getter.connect("progress", self._download_progress_cb, tube_id)
        getter.connect("error", self._download_error_cb, tube_id)
        _logger.debug("Starting download to %s...", path)
        getter.start(path)
        self._download_content_length = getter.get_content_length()
        self._download_content_type = getter.get_content_type()
        return False

    def _get_document(self):
        if not self._want_document:
            return False

        # Assign a file path to download if one doesn't exist yet
        if not self._jobject.file_path:
            path = os.path.join(self.get_activity_root(), 'instance',
                                'tmp%i' % time.time())
        else:
            path = self._jobject.file_path

        # Pick an arbitrary tube we can try to download the document from
        try:
            tube_id = self.unused_download_tubes.pop()
        except (ValueError, KeyError), e:
            _logger.debug('No tubes to get the document from right now: %s',
                          e)
            return False

        # Avoid trying to download the document multiple times at once
        self._want_document = False
        gobject.idle_add(self._download_document, tube_id, path)
        return False

    def _joined_cb(self, also_self):
        """Callback for when a shared activity is joined.

        Get the shared document from another participant.
        """
        self.watch_for_tubes()
        gobject.idle_add(self._get_document)


    def _load_document(self, filepath):
        """Load the specified document and set up the UI.

        filepath -- string starting with file://

        """
        filename = filepath.replace('file://', '')
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            return
        mimetype = mime.get_for_file(filepath)
        self._mimetype = mimetype
        if mimetype == 'application/epub+zip':
            self._view = epubadapter.EpubViewer()
        elif mimetype == 'text/plain' or mimetype == 'application/zip':
            self._view = textadapter.TextViewer()
        else:
            self._view = evinceadapter.EvinceViewer()

        self._view.setup(self)
        self._view.load_document(filepath)

        self._want_document = False

        self._view_toolbar.set_view(self._view)
        self._edit_toolbar.set_view(self._view)

        self._topbar.set_view(self._view)

        filehash = get_md5(filepath)
        self._annotationmanager = AnnotationManager(filehash, self._mimetype, self._sidebar)
        self._sidebar.set_annotationmanager(self._annotationmanager)
        self._update_nav_buttons()
        self._update_toc()
        self._view.connect_page_changed_handler(self.__page_changed_cb)
        self._view.load_metadata(self)
        self._update_toolbars()

        self._edit_toolbar._search_entry.props.text = \
                                self.metadata.get('Anno_search', '')

        current_page = int(self.metadata.get('Anno_current_page', '0'))
        _logger.debug('Setting page to: %d', current_page)
        self._view.set_current_page(current_page)

        # We've got the document, so if we're a shared activity, offer it
        try:
            if self.get_shared():
                self.watch_for_tubes()
                self._share_document()
        except Exception, e:
            _logger.debug('Sharing failed: %s', e)

    def _update_toolbars(self):
        self._view_toolbar._update_zoom_buttons()
        if not self._view.can_highlight():
            self._highlight_item.hide()
        if speech.supported and self._view.can_do_text_to_speech():
            self.speech_toolbar_button.show()
            self.speech_toolbar_button.show()

    def _share_document(self):
        """Share the document."""
        # FIXME: should ideally have the fileserver listen on a Unix socket
        # instead of IPv4 (might be more compatible with Rainbow)

        _logger.debug('Starting HTTP server on port %d', self.port)
        self._fileserver = AnnoHTTPServer(("", self.port),
            self._tempfile)

        # Make a tube for it
        chan = self.shared_activity.telepathy_tubes_chan
        iface = chan[telepathy.CHANNEL_TYPE_TUBES]
        self._fileserver_tube_id = iface.OfferStreamTube(READ_STREAM_SERVICE,
                {},
                telepathy.SOCKET_ADDRESS_TYPE_IPV4,
                ('127.0.0.1', dbus.UInt16(self.port)),
                telepathy.SOCKET_ACCESS_CONTROL_LOCALHOST, 0)

    def watch_for_tubes(self):
        """Watch for new tubes."""
        tubes_chan = self.shared_activity.telepathy_tubes_chan

        tubes_chan[telepathy.CHANNEL_TYPE_TUBES].connect_to_signal('NewTube',
            self._new_tube_cb)
        tubes_chan[telepathy.CHANNEL_TYPE_TUBES].ListTubes(
            reply_handler=self._list_tubes_reply_cb,
            error_handler=self._list_tubes_error_cb)

    def _new_tube_cb(self, tube_id, initiator, tube_type, service, params,
                     state):
        """Callback when a new tube becomes available."""
        _logger.debug('New tube: ID=%d initator=%d type=%d service=%s '
                      'params=%r state=%d', tube_id, initiator, tube_type,
                      service, params, state)
        if self._document is None and service == READ_STREAM_SERVICE:
            _logger.debug('I could download from that tube')
            self.unused_download_tubes.add(tube_id)
            # if no download is in progress, let's fetch the document
            if self._want_document:
                gobject.idle_add(self._get_document)

    def _list_tubes_reply_cb(self, tubes):
        """Callback when new tubes are available."""
        for tube_info in tubes:
            self._new_tube_cb(*tube_info)

    def _list_tubes_error_cb(self, e):
        """Handle ListTubes error by logging."""
        _logger.error('ListTubes() failed: %s', e)

    def _shared_cb(self, activityid):
        """Callback when activity shared.

        Set up to share the document.

        """
        # We initiated this activity and have now shared it, so by
        # definition we have the file.
        _logger.debug('Activity became shared')
        self.watch_for_tubes()
        self._share_document()

    def _view_selection_changed_cb(self, view):
        self._edit_toolbar.copy.props.sensitive = view.get_has_selection()
        if self._view.can_highlight():
            # Verify if the selection already exist or the cursor
            # is in a highlighted area
            cursor_position = self._view.get_cursor_position()
            logging.debug('cursor position %d' % cursor_position)
            selection_tuple = self._view.get_selection_bounds()
            tuples_list = self._annotationmanager.get_highlights( \
                    self._view.get_current_page())
            in_bounds = False
            for highlight_tuple in tuples_list:
                logging.debug('control tuple  %s' % str(highlight_tuple))
                if selection_tuple:
                    if selection_tuple[0] >= highlight_tuple[0] and \
                       selection_tuple[1] <= highlight_tuple[1]:
                        in_bounds = True
                        break
                if cursor_position >= highlight_tuple[0] and \
                   cursor_position <= highlight_tuple[1]:
                    in_bounds = True
                    break

            self._highlight.props.sensitive = \
                    view.get_has_selection() or in_bounds

            self._highlight.handler_block(self._highlight_id)
            self._highlight.set_active(in_bounds)
            self._highlight.handler_unblock(self._highlight_id)

    def _edit_toolbar_copy_cb(self, button):
        self._view.copy()

    def _key_press_event_cb(self, widget, event):
        keyname = gtk.gdk.keyval_name(event.keyval)
        if keyname == 'c' and event.state & gtk.gdk.CONTROL_MASK:
            self._view.copy()
            return True
        elif keyname == 'KP_Home':
            # FIXME: refactor later to self.zoom_in()
            self._view_toolbar.zoom_in()
            return True
        elif keyname == 'KP_End':
            self._view_toolbar.zoom_out()
            return True
        elif keyname == 'Home':
            self._view.scroll(gtk.SCROLL_START, False)
            return True
        elif keyname == 'End':
            self._view.scroll(gtk.SCROLL_END, False)
            return True
        elif keyname == 'Page_Up' or keyname == 'KP_Page_Up':
            self._view.scroll(gtk.SCROLL_PAGE_BACKWARD, False)
            return True
        elif keyname == 'Page_Down' or keyname == 'KP_Page_Down':
            self._view.scroll(gtk.SCROLL_PAGE_FORWARD, False)
            return True
        elif keyname == 'Up' or keyname == 'KP_Up':
            self._view.scroll(gtk.SCROLL_STEP_BACKWARD, False)
            return True
        elif keyname == 'Down' or keyname == 'KP_Down':
            self._view.scroll(gtk.SCROLL_STEP_FORWARD, False)
            return True
        elif keyname == 'Left' or keyname == 'KP_Left':
            self._view.scroll(gtk.SCROLL_STEP_BACKWARD, True)
            return True
        elif keyname == 'Right' or keyname == 'KP_Right':
            self._view.scroll(gtk.SCROLL_STEP_FORWARD, True)
            return True
        else:
            return False

    def _key_release_event_cb(self, widget, event):
        #keyname = gtk.gdk.keyval_name(event.keyval)
        #_logger.debug("Keyname Release: %s, time: %s", keyname, event.time)
        return False

    def __view_toolbar_needs_update_size_cb(self, view_toolbar):
        if hasattr(self._view, 'update_view_size'):
            self._view.update_view_size(self._scrolled)
        else:
            return False # No need to run this again and again

    def __view_toolbar_go_fullscreen_cb(self, view_toolbar):
        self.fullscreen()
