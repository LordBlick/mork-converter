import warnings
import re

import morkast

class _MorkDict(dict):
    def __init__(self):
        dict.__init__(self)

        # I'm not really sure this initialization is right.
        for i in xrange(0x80):
            col = '%X' % i
            value = chr(i)
            self[col] = value

    @staticmethod
    def fromAst(ast, db):
        assert isinstance(ast, morkast.Dict)

        # Create a _MorkDict from ast.cells
        cells = _MorkDict()
        for cell in ast.cells:
            cells[cell.column] = db._unescape(cell.value)
            if cell.cut:
                warnings.warn("ignoring cell's 'cut' attribute")

        # Find the namespace (if any) in ast.meta
        namespace = 'a'
        assert len(ast.meta) <= 1, 'multiple meta-dicts'
        if ast.meta:
            for cell in ast.meta[0].cells:
                if cell.column == 'a':
                    namespace = cell.value
                    break

        existing = db.dicts.get(namespace)
        if existing is None:
            db.dicts[namespace] = cells
        else:
            existing.update(cells)

class _MorkStore(object):
    def __init__(self):
        # I think this will be sort of like { (namespace, id): morkObject }
        self._store = {} # { 'namespace': { 'id': object } }

    def __getitem__(self, key):
        (namespace, oid) = key
        return self._store[namespace][oid]

    def __setitem__(self, key, value):
        (namespace, oid) = key
        self._store.setdefault(namespace, {})[oid] = value

class _MorkTableStore(_MorkStore):
    pass

class _MorkRowStore(_MorkStore):
    pass

class _MorkTable(object):
    def __init__(self, rows=None):
        if rows is None:
            rows = []

        self._rows = rows

    def columnNames(self):
        columns = set()
        for row in self._rows:
            columns.update(row.columnNames())

        return columns

    def addRow(self, row):
        self._rows.append(row)

    @staticmethod
    def fromAst(ast, db):
        assert isinstance(ast, morkast.Table)

        # Get id and namespace
        (oid, namespace) = db._dissectId(ast.tableid)
        assert namespace is not None, 'no namespace found for table'

        rows = []
        for row in ast.rows:
            # row could be ObjectId or Row
            if isinstance(row, morkast.ObjectId):
                (rowId, rowNamespace) = db._dissectId(row)
                if rowNamespace is None:
                    rowNamespace = namespace
                newRow = db.rows[rowNamespace, rowId]
            else:
                newRow = _MorkRow.fromAst(row, db, namespace)

            rows.append(newRow)

        self = _MorkTable(rows)

        if ast.trunc:
            warnings.warn("ignoring table's 'truncated' attribute")
        if ast.meta:
            warnings.warn('ignoring meta-table')

        # Insert into table store
        db.tables[namespace, oid] = self

        return self

class _MorkRow(dict):
    def __init__(self):
        dict.__init__(self)

    def columnNames(self):
        return self.keys()

    @staticmethod
    def fromAst(ast, db, defaultNamespace=None):
        assert isinstance(ast, morkast.Row)

        self = _MorkRow()
        for cell in ast.cells:
            (column, value) = db._inflateCell(cell)
            self[column] = value

        # Get id and namespace
        (oid, namespace) = db._dissectId(ast.rowid)
        if namespace is None:
            namespace = defaultNamespace

        assert namespace is not None, 'no namespace found for row'

        if ast.trunc:
            warnings.warn("ignoring row's 'trucated' attribute")
        if ast.cut:
            warnings.warn("ignoring row's 'cut' attribute")
        if ast.meta:
            warnings.warn('ignoring meta-row')

        # insert into row store
        db.rows[namespace, oid] = self

        return self

class MorkDatabase(object):
    def __init__(self):
        self.dicts = {} # { 'namespace': _MorkDict }
        self.tables = _MorkTableStore()
        self.rows = _MorkRowStore()
        #self.groups = {}

        self.dicts['a'] = _MorkDict()
        self.dicts['c'] = _MorkDict()

    # **** A bunch of utility methods ****

    def _dictDeref(self, objref, defaultNamespace='c'):
        assert isinstance(objref, morkast.ObjectRef)

        (oid, namespace) = self._dissectId(objref.obj)
        if namespace is None:
            namespace = defaultNamespace

        return self.dicts[namespace][oid]

    def _dissectId(self, oid):
        '''
        Return ('objectId', 'namespace') or ('objectId', None) if the
        namespace cannot be determined.
        '''
        assert isinstance(oid, morkast.ObjectId)

        namespace = oid.scope
        if isinstance(namespace, morkast.ObjectRef):
            namespace = self._dictDeref(namespace)

        return (oid.objectid, namespace)

    _unescapeMap = {
        r'\)': ')', r'\\': '\\', r'\$': '$', # basic escapes
        '\\\r\n': '', '\\\n': '',            # line continuation
    }
    def _translateEscape(self, match):
        text = match.group()
        if text.startswith('$'):
            return chr(int(text[1:], 16))

        return self._unescapeMap[text]

    _escape = re.compile(r'\$[0-9a-fA-F]{2}|\\\r\n|\\.', re.DOTALL)
    def _unescape(self, value):
        return self._escape.sub(self._translateEscape, value)

    def _inflateCell(self, cell):
        column = cell.column
        if isinstance(column, morkast.ObjectRef):
            column = self._dictDeref(column)

        value = cell.value
        if isinstance(value, morkast.ObjectRef):
            value = self._dictDeref(value, 'a')
        else:
            value = self._unescape(value)

        return (column, value)

    # **** Database builder ****

    _builder = {
        morkast.Dict:  _MorkDict.fromAst,
        morkast.Row:   _MorkRow.fromAst,
        morkast.Table: _MorkTable.fromAst,
    }

    @staticmethod
    def fromAst(ast):
        assert isinstance(ast, morkast.Database)

        self = MorkDatabase()

        for item in ast.items:
            builder = self._builder.get(item.__class__)
            if builder is None:
                warnings.warn('skipping item of type %s' % item.__class__)
                continue

            builder(item, self)

        return self


# Test
import sys

import morkyacc

def main(args=None):
    if args is None:
        args = sys.argv[1:]

    tree = morkyacc.parseFile(args[0])
    db = MorkDatabase.fromAst(tree)

    import pdb
    pdb.set_trace()

    return 0

if __name__ == '__main__':
    sys.exit(main())