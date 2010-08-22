# Copyright 2010 Kevin Goodsell

# This file is part of mork-converter.
#
# mork-converter is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License Version 2 as published
# by the Free Software Foundation.
#
# mork-converter is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mork-converter.  If not, see <http://www.gnu.org/licenses/>.

import warnings
import time
import optparse

from filterbase import Filter

# Converters for different field types:

class _FieldConverter(object):
    def convert(self, opts, value):
        raise NotImplementedError();

class _Int(_FieldConverter):
    def __init__(self, base):
        self._base = base

    def convert(self, opts, value):
        if opts.no_base:
            return value

        return unicode(self._to_int(value))

    def _to_int(self, value):
        return int(value, self._base)

class _SignedInt32(_Int):
    def convert(self, opts, value):
        if opts.no_base:
            return value

        ival = self._to_int(value)
        assert ival <= 0xffffffff, 'integer too large for 32 bits'
        if ival > 0x7fffffff:
            ival -= 0x100000000

        return unicode(ival)

class _HierDelim(_Int):
    def __init__(self):
        _Int.__init__(self, 16)

    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        ival = self._to_int(value)
        cval = unichr(ival)
        if cval == u'^':
            return u'kOnlineHierarchySeparatorUnknown'
        elif cval == u'|':
            return u'kOnlineHierarchySeparatorNil'
        else:
            return cval

class _Flags(_Int):
    def __init__(self, values, empty=u'', base=16):
        _Int.__init__(self, base)

        self._empty = empty
        self._values = list(values)

    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        ival = self._to_int(value)
        flags = self._get_flags(opts, ival)
        if flags:
            return u' '.join(flags)
        else:
            return self._empty

    def _get_flags(self, opts, ival):
        result = []
        for (i, flag) in enumerate(self._values):
            if not flag:
                continue

            fval = 1 << i
            if fval & ival:
                result.append(flag)
                ival -= fval

        if ival:
            warnings.warn('unknown flags: %x' % ival)

        return result

# mailnews/base/public/nsMsgMessageFlags.idl nsMsgMessageFlags
# Message "flags" include some non-flag parts.
class _MsgFlags(_Flags):
    _flag_vals = [u'Read', u'Replied', u'Marked', u'Expunged', u'HasRe',
                  u'Elided', None, u'Offline', u'Watched', u'SenderAuthed',
                  u'Partial', u'Queued', u'Forwarded', None, None, None,
                  u'New', None, u'Ignored', None, None, u'IMAPDeleted',
                  u'MDNReportNeeded', u'MDNReportSent', u'Template',
                  None, None, None, u'Attachment']

    # mailnews/base/public/MailNewsTypes2.idl
    _priority_labels = ['notSet', 'none', 'lowest', 'low', 'normal', 'high',
                        'highest']

    def __init__(self):
        _Flags.__init__(self, self._flag_vals)

    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        ival = self._to_int(value)
        # Deal with non-flags:
        # Priorities = 0xE000
        priorities = ival & 0xE000
        ival -= priorities
        priorities >>= 13
        assert priorities < len(self._priority_labels), 'invalid priority'
        # Labels = 0xE000000
        labels = ival & 0xE000000
        ival -= labels
        labels >>= 25

        flags = self._get_flags(opts, ival)

        if priorities:
            flags.append('Priorities:%s' % self._priority_labels[priorities])
        if labels:
            flags.append('Labels:0x%X' % labels)

        return u' '.join(flags)

class _ImapFlags(_Flags):
    _flag_vals = ['kImapMsgSeenFlag', 'kImapMsgAnsweredFlag',
                  'kImapMsgFlaggedFlag', 'kImapMsgDeletedFlag',
                  'kImapMsgDraftFlag', 'kImapMsgRecentFlag',
                  'kImapMsgForwardedFlag', 'kImapMsgMDNSentFlag',
                  'kImapMsgCustomKeywordFlag', None, None, None, None,
                  'kImapMsgSupportMDNSentFlag', 'kImapMsgSupportForwardedFlag',
                  'kImapMsgSupportUserFlag']

    def __init__(self):
        _Flags.__init__(self, self._flag_vals, 'kNoImapMsgFlag')

    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        ival = self._to_int(value)
        # Handle labels
        labels = ival & 0xE00
        ival -= labels
        labels >>= 9

        flags = self._get_flags(opts, ival)

        if labels:
            flags.append('Labels:0x%X' % labels)

        return u' '.join(flags)

class _Enumeration(_Int):
    def __init__(self, values, default=None, base=16):
        _Int.__init__(self, base)

        if isinstance(values, dict):
            self._map = dict(values)
        else:
            self._map = dict(enumerate(values))

        self._default = default

    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        if value == '':
            result = self._default
        else:
            ival = self._to_int(value)
            result = self._map.get(ival, self._default)

        if result is None:
            # No conversion
            return value
        else:
            return result

class _BoolInt(_Enumeration):
    def __init__(self):
        _Enumeration.__init__(self, [u'false', u'true'])

# This is for fields that signal something by their mere presence. The value
# doesn't matter.
class _BoolAnyVal(_FieldConverter):
    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        return u'true'

class _Time(_FieldConverter):
    def _format(self, opts, t):
        return time.strftime(opts.time_format, t)

class _Seconds(_Time):
    def __init__(self, base=10, divisor=1):
        self._base = base
        self._divisor = divisor

    def convert(self, opts, value):
        if opts.no_time:
            return value

        # 0 is a common value, and obviously doesn't represent a valid time.
        if value == '0':
            return value

        seconds = int(value, self._base) / self._divisor
        t = time.localtime(seconds)

        return self._format(opts, t)

class _FormattedTime(_Time):
    def __init__(self, parse_format):
        self._parse_format = parse_format

    def convert(self, opts, value):
        if opts.no_time:
            return value

        t = time.strptime(value, self._parse_format)
        return self._format(opts, t)

class _SortColumns(_FieldConverter):
    # constants from mailnews/base/public/nsIMsgDBView.idl.
    _sort_order = {
        0 : 'none',
        1 : 'ascending',
        2 : 'descending',
    }

    _sort_type = {
        0x11 : 'byNone',
        0x12 : 'byDate',
        0x13 : 'bySubject',
        0x14 : 'byAuthor',
        0x15 : 'byId',
        0x16 : 'byThread',
        0x17 : 'byPriority',
        0x18 : 'byStatus',
        0x19 : 'bySize',
        0x1a : 'byFlagged',
        0x1b : 'byUnread',
        0x1c : 'byRecipient',
        0x1d : 'byLocation',
        0x1e : 'byTags',
        0x1f : 'byJunkStatus',
        0x20 : 'byAttachments',
        0x21 : 'byAccount',
        0x22 : 'byCustom',
        0x23 : 'byReceived',
    }

    def convert(self, opts, value):
        if opts.no_symbolic:
            return value

        sort_items = []

        for piece in value.split('\r'):
            it = iter(piece)
            for isort_type in it:
                isort_order = ord(next(it)) - ord('0')

                sort_type = self._sort_type.get(ord(isort_type))
                sort_order = self._sort_order.get(isort_order)

                assert sort_type is not None, 'invalid sort type'
                assert sort_order is not None, 'invalid sort order'

                sort_item = u'type:%s order:%s' % (sort_type, sort_order)

                if sort_type == 'byCustom':
                    # The rest is the custom column name (or something like
                    # that).
                    custom_col = str(it)
                    sort_item = '%s custom:%s' % (sort_item, custom_col)

                sort_items.append(sort_item)

        return u', '.join(sort_items)

_hex_int_converter = _Int(base=16)
_signed_int32_converter = _SignedInt32(base=16)
_msg_flags_converter = _MsgFlags()
_bool_int_converter = _BoolInt()
_bool_any_converter = _BoolAnyVal()
_seconds_converter = _Seconds()
_hex_seconds_converter = _Seconds(base=16)
_microseconds_converter = _Seconds(divisor=1000000)
_purge_time_converter = _FormattedTime('%a %b %d %H:%M:%S %Y')
# mailnews/base/public/nsMsgFolderFlags.idl
_msg_folder_flags_converter = _Flags(['Newsgroup', 'NewsHost', 'Mail',
                                      'Directory', 'Elided', 'Virtual',
                                      'Subscribed', 'Unused2', 'Trash',
                                      'SentMail', 'Drafts', 'Queue', 'Inbox',
                                      'ImapBox', 'Archive', 'ProfileGroup',
                                      'Unused4', 'GotNew', 'ImapServer',
                                      'ImapPersonal', 'ImapPublic',
                                      'ImapOtherUser', 'Templates',
                                      'PersonalShared', 'ImapNoselect',
                                      'CreatedOffline', 'ImapNoinferiors',
                                      'Offline', 'OfflineEvents', 'CheckNew',
                                      'Junk', 'Favorite'])

# The big dictionary of field converters.
#
# Note: ns:addrbk, ns:history, ns:formhistory are pretty obvious, but ns:msg
# is used for both Mail Summary Files and Folder Caches. However, Folder Caches
# have :scope:folders and Mail Summary Files have several scopes, none of which
# are 'folders'.

_converters = {
    # Address Book Fields (ns:addrbk).
    # Source references are for Thunderbird 3.0.5 unless otherwise
    # indicated.
    'ns:addrbk:db:row:scope:card:all' : {
        # mailnews/addrbook/src/nsAddrDatabase.h AddAllowRemoteContent
        'AllowRemoteContent' : _bool_int_converter,
        # Based on mailnews/addrbook/src/nsAddrDatabase.h AddCardType from
        # Thunderbird 2.0.0.24, CardType appears to be a string. However,
        # based on calls to GetCardTypeFromString in
        # mailnews/addrbook/src/nsAbCardProperty.cpp, and the definition of
        # constants in mailnews/addrbook/public/nsIAbCard.idl, it appears to be
        # an enumeration with a bizarre string-formatted integer internal
        # representation.
        'CardType'           : _Enumeration([u'normal', u'AOL groups',
                                             u'AOL additional email'],
                                            default=u'normal'),
        # mailnews/addrbook/src/nsAddrDatabase.cpp AddRowToDeletedCardsTable
        'LastModifiedDate'   : _hex_seconds_converter,
        # mailnews/addrbook/src/nsAddrDatabase.h AddPopularityIndex
        'PopularityIndex'    : _hex_int_converter,
        # mailnews/addrbook/src/nsAbCardProperty.cpp ConvertToEscapedVCard
        'PreferMailFormat'   : _Enumeration([u'unknown', u'plaintext',
                                             u'html']),
    },
    'ns:addrbk:db:row:scope:list:all' : {
        # mailnews/addrbook/src/nsAddrDatabase.cpp GetListAddressTotal
        'ListTotalAddresses' : _hex_int_converter,
    },

    # History Fields (ns:history).
    # Source references are from Firefox 2.0.0.20 unless otherwise indicated.
    'ns:history:db:row:scope:history:all' : {
        # Tokens are created in
        # /toolkit/components/history/src/nsGlobalHistory.cpp CreateTokens.
        # AddNewPageToDatabase in the same file is a good reference for these.

        'FirstVisitDate' : _microseconds_converter,
        'LastVisitDate'  : _microseconds_converter,
        'Hidden'         : _bool_any_converter,
        'Typed'          : _bool_any_converter,
    },

    # Folder Cache Fields (ns:msg:db:row:scope:folders:).
    # Source references are from Thunderbird 3.0.5 unless otherwise indicated.
    # Folder caches seem to share a lot of attributes with
    # ns:msg:db:row:scope:dbfolderinfo from .msf files.
    'ns:msg:db:row:scope:folders:all' : {
        # From mailnews/db/msgdb/src/nsMsgDatabase.cpp
        'LastPurgeTime'     : _purge_time_converter,
        # Defined in mailnews/base/public/msgCore.h, used
        # in mailnews/base/util/nsMsgDBFolder.cpp
        'MRUTime'           : _seconds_converter,
        # This shows up in mailnews/imap/src/nsImapMailFolder.cpp.
        # Flag values are defined in mailnews/imap/src/nsImapMailFolder.h.
        'aclFlags'          : _Flags(['IMAP_ACL_READ_FLAG',
                                      'IMAP_ACL_STORE_SEEN_FLAG',
                                      'IMAP_ACL_WRITE_FLAG',
                                      'IMAP_ACL_INSERT_FLAG',
                                      'IMAP_ACL_POST_FLAG',
                                      'IMAP_ACL_CREATE_SUBFOLDER_FLAG',
                                      'IMAP_ACL_DELETE_FLAG',
                                      'IMAP_ACL_ADMINISTER_FLAG',
                                      'IMAP_ACL_RETRIEVED_FLAG',
                                      'IMAP_ACL_EXPUNGE_FLAG',
                                      'IMAP_ACL_DELETE_FOLDER']),
        # From mailnews/imap/src/nsImapMailFolder.cpp. Flags defined in
        # mailnews/imap/src/nsImapCore.h.
        'boxFlags'          : _Flags(['kMarked', 'kUnmarked', 'kNoinferiors',
                                      'kNoselect', 'kImapTrash',
                                      'kJustExpunged', 'kPersonalMailbox',
                                      'kPublicMailbox', 'kOtherUsersMailbox',
                                      'kNameSpace', 'kNewlyCreatedFolder',
                                      'kImapDrafts', 'kImapSpam', 'kImapSent',
                                      'kImapInbox', 'kImapAllMail',
                                      'kImapXListTrash'],
                                     'kNoFlags'),
        # From mailnews/imap/src/nsImapMailFolder.cpp, with constants in
        # mailnews/imap/src/nsImapCore.h
        'hierDelim'         : _HierDelim(),

        # The remaining items are all from mailnews/base/util/nsMsgDBFolder.cpp

        # Flags are found in mailnews/base/public/nsMsgFolderFlags.idl.
        'flags'             : _msg_folder_flags_converter,
        'totalMsgs'         : _signed_int32_converter,
        'totalUnreadMsgs'   : _signed_int32_converter,
        'pendingUnreadMsgs' : _signed_int32_converter,
        'pendingMsgs'       : _signed_int32_converter,
        'expungedBytes'     : _hex_int_converter,
        'folderSize'        : _hex_int_converter,
    },

    # Mail Summary File Fields
    # (ns:msg:db:row:scope:{dbfolderinfo,msgs,threads})
    # Source references are for Thunderbird 3.0.5 unless otherwise indicated.
    'ns:msg:db:row:scope:dbfolderinfo:all' : {
        # current-view seems to have duplicate definitions in
        # suite/mailnews/msgViewPickerOverlay.js and
        # mail/base/modules/mailViewManager.js.
        'current-view'         : _Enumeration([u'kViewItemAll',
                                               u'kViewItemUnread',
                                               u'kViewItemTags',
                                               u'kViewItemNotDeleted',
                                               None, None, None,
                                               u'kViewItemVirtual',
                                               u'kViewItemCustomize',
                                               u'kViewItemFirstCustom']),
        # The next several are from mailnews/db/msgdb/src/nsMsgDatabase.cpp
        # GetMsgRetentionSetting.
        # retainBy enum comes from mailnews/db/msgdb/public/nsIMsgDatabase.idl.
        'retainBy'             : _Enumeration([None, 'nsMsgRetainAll',
                                               'nsMsgRetainByAge',
                                               'nsMsgRetainByNumHeaders']),
        'daysToKeepHdrs'       : _hex_int_converter,
        'numHdrsToKeep'        : _hex_int_converter,
        'daysToKeepBodies'     : _hex_int_converter,
        'keepUnreadOnly'       : _bool_int_converter,
        'useServerDefaults'    : _bool_int_converter,
        'cleanupBodies'        : _bool_int_converter,

        # The next several are shared with ns:msg:db:row:scope:folders:all
        'LastPurgeTime'        : _purge_time_converter,
        'MRUTime'              : _seconds_converter,
        'expungedBytes'        : _hex_int_converter,
        'flags'                : _msg_folder_flags_converter,
        'folderSize'           : _hex_int_converter,

        # The next several are from mailnews/db/msgdb/src/nsDBFolderInfo.cpp.
        'numMsgs'              : _hex_int_converter,
        'numNewMsgs'           : _hex_int_converter,
        'folderDate'           : _hex_seconds_converter,
        'charSetOverride'      : _bool_int_converter,
        # Enum and flag values are in mailnews/base/public/nsIMsgDBView.idl
        'viewType'             : _Enumeration(['eShowAllThreads', None,
                                               'eShowThreadsWithUnread',
                                               'eShowWatchedThreadsWithUnread',
                                               'eShowQuickSearchResults',
                                               'eShowVirtualFolderResults',
                                               'eShowSearch']),
        'viewFlags'            : _Flags(['kThreadedDisplay', None, None,
                                         'kShowIgnored', 'kUnreadOnly',
                                         'kExpandAll', 'kGroupBySort'],
                                        'kNone'),
        'sortType'             : _Enumeration([{0x11 : 'byNone',
                                                0x12 : 'byDate',
                                                0x13 : 'bySubject',
                                                0x14 : 'byAuthor',
                                                0x15 : 'byId',
                                                0x16 : 'byThread',
                                                0x17 : 'byPriority',
                                                0x18 : 'byStatus',
                                                0x19 : 'bySize',
                                                0x1a : 'byFlagged',
                                                0x1b : 'byUnread',
                                                0x1c : 'byRecipient',
                                                0x1d : 'byLocation',
                                                0x1e : 'byTags',
                                                0x1f : 'byJunkStatus',
                                                0x20 : 'byAttachments',
                                                0x21 : 'byAccount',
                                                0x22 : 'byCustom',
                                                0x23 : 'byReceived'}]),
        'sortOrder'            : _Enumeration(['none', 'ascending',
                                               'descending']),

        # From mailnews/db/msgdb/src/nsMsgDatabase.cpp.
        'fixedBadRefThreading' : _bool_int_converter,

        # From mailnews/imap/src/nsImapMailFolder.cpp.
        # Flags are in mailnews/imap/src/nsImapCore.h.
        'imapFlags'            : _ImapFlags(),
        # From mailnews/base/src/nsMsgDBView.cpp, using consants from
        # mailnews/base/public/nsIMsgDBView.idl. DecodeColumnSort describes how
        # to handle this.
        'sortColumns'          : _SortColumns(),
    },
    'ns:msg:db:row:scope:msgs:all' : {
        # mailnews/imap/src/nsImapMailFolder.cpp
        'ProtoThreadFlags'    : _msg_flags_converter,

        # The next several are defined in
        # mailnews/db/msgdb/src/nsMsgDatabase.cpp and are actually used in
        # mailnews/db/msgdb/src/nsMsgHdr.cpp.
        'date'                : _hex_seconds_converter,
        'size'                : _hex_int_converter,
        'flags'               : _msg_flags_converter,
        'priority'            : _Enumeration(['notSet', 'none', 'lowest',
                                              'low', 'normal', 'high',
                                              'highest']),
        'label'               : _hex_int_converter,
        'statusOfset'         : _hex_int_converter,
        'numLines'            : _hex_int_converter,
        'msgOffset'           : _hex_int_converter,
        'offlineMsgSize'      : _hex_int_converter,
        # Same files, but Thunderbird 2.0.0.24.
        'numRefs'             : _hex_int_converter,

        # From mailnews/local/src/nsParseMailbox.cpp
        'dateReceived'        : _hex_seconds_converter,
        # From mailnews/base/src/nsMsgContentPolicy.cpp
        'remoteContentPolicy' : _Enumeration(['kNoRemoteContentPolicy',
                                              'kBlockRemoteContent',
                                              'kAllowRemoteContent']),
    },

    # Mail Summary File meta-rows.
    'm' : {
        # These are all declared in mailnews/db/msgdb/src/nsMsgDatabase.cpp
        # and read in in mailnews/db/msgdb/src/nsMsgThread.cpp
        # InitCachedValues.
        'children'            : _hex_int_converter,
        'unreadChildren'      : _hex_int_converter,
        'threadFlags'         : _msg_flags_converter,
        'threadNewestMsgDate' : _hex_seconds_converter,
    },
}

class FieldConverter(Filter):
    '''
    Filter to interpret Mork fields, making them more human-readable.
    '''
    def __init__(self, order):
        self.mork_filter_order = order

    def add_options(self, parser):
        group = optparse.OptionGroup(parser, 'Field Conversion Options')

        group.add_option('-x', '--no-convert', action='store_true',
            help="don't do any of the usual field conversions")
        group.add_option('--no-time', action='store_true',
            help="don't do time/date conversions")
        group.add_option('--time-format', metavar='FORMAT',
            help='use FORMAT as the strftime format for times/dates '
                 '(default: %c)')
        group.add_option('--no-base', action='store_true',
            help="don't convert hexidecimal integers to decimal")
        group.add_option('--no-symbolic', action='store_true',
            help="don't do symbolic conversions (e.g. flags, booleans, and "
                 "number-to-string conversions)")

        parser.add_option_group(group)
        parser.set_defaults(time_format='%c')

    def process(self, db, opts):
        if opts.no_convert:
            return

        for (row_namespace, row_id, row) in db.rows.items():
            row_converters = _converters.get(row_namespace)
            if row_converters is None:
                continue

            for (col, value) in row.items():
                converter = row_converters.get(col)
                if converter:
                    row[col] = converter.convert(opts, value)

convert_fields = FieldConverter(4200)