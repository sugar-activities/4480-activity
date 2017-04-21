import logging
import time

import gtk
from sugar.graphics import style
from sugar.graphics.xocolor import XoColor
from sugar.graphics.icon import _IconBuffer, Icon

_logger = logging.getLogger('anno-activity')


class AnnoIcon(gtk.EventBox):
    __gtype_name__  = 'SugarAnnoIcon'
    annotation      = None
    _event_cb_id    = None
    _tooltip_cb_id  = None

    def __init__(self, icon_name=None, xo_color=None, annotation=None, event_cb=None):
        gtk.EventBox.__init__(self)

        self.__event_cb = event_cb
        self.annotation = annotation 
        #self.set_size_request(20, -1)
        self.set_size_request(20, 20)
        # Take care of the background first
        white = gtk.gdk.color_parse("white")
        self.modify_bg(gtk.STATE_NORMAL, white)
 
        self.set_app_paintable(True)

        self._icon = Icon(icon_name=icon_name, xo_color=xo_color,
                          pixel_size=18) #gtk.ICON_SIZE_LARGE_TOOLBAR
                          #icon_size=style.SMALL_ICON_SIZE) #gtk.ICON_SIZE_LARGE_TOOLBAR
        self._icon.props.has_tooltip = True
        self._tooltip_cb_id = self._icon.connect('query_tooltip', self.__annotation_icon_query_tooltip_cb)
        
        self._event_cb_id = self.connect('event', self.__event_cb, self.annotation)
 
        self.add(self._icon)
        self._icon.show()
        self.add_events(gtk.gdk.BUTTON_PRESS_MASK)


    def get_icon(self):
        return self._icon


    def __annotation_icon_query_tooltip_cb(self, widget, x, y, keyboard_mode, tip):
        tooltip_header  = self.annotation.get_note_title()
        tooltip_body    = self.annotation.get_note_body()
        
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

        tip.set_custom(vbox)

        return True
    

    def _disconnect(self):
        self._icon.disconnect(self._tooltip_cb_id)
        self.disconnect(self._event_cb_id)
        _logger.debug('disconnecting icon: %d' % self._event_cb_id ) 
