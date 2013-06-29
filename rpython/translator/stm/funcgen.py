from rpython.translator.c.support import c_string_constant, cdecl
from rpython.translator.c.node import ContainerNode
from rpython.translator.c.primitive import name_small_integer


class StmHeader_OpaqueNode(ContainerNode):
    nodekind = 'stmhdr'
    globalcontainer = True
    typename = 'struct stm_object_s @'
    implementationtypename = typename
    _funccodegen_owner = None

    def __init__(self, db, T, obj):
        assert isinstance(obj._name, int)
        self.db = db
        self.T = T
        self.obj = obj

    def initializationexpr(self, decoration=''):
        yield '{ %s | PREBUILT_FLAGS, PREBUILT_REVISION, %dL }' % (
            name_small_integer(self.obj.typeid16, self.db),
            self.obj.prebuilt_hash)


def stm_initialize(funcgen, op):
    return 'stm_initialize();'

_STM_BARRIER_FUNCS = {   # XXX try to see if some combinations can be shorter
    'P2R': 'stm_read_barrier',
    'G2R': 'stm_read_barrier',
    'O2R': 'stm_read_barrier',
    'P2W': 'stm_write_barrier',
    'G2W': 'stm_write_barrier',
    'O2W': 'stm_write_barrier',
    'R2W': 'stm_write_barrier',
    }

def stm_barrier(funcgen, op):
    category_change = op.args[0].value
    funcname = _STM_BARRIER_FUNCS[category_change]
    assert op.args[1].concretetype == op.result.concretetype
    arg = funcgen.expr(op.args[1])
    result = funcgen.expr(op.result)
    return '%s = (%s)%s((gcptr)%s);' % (
        result, cdecl(funcgen.lltypename(op.result), ''),
        funcname, arg)

def stm_ptr_eq(funcgen, op):
    arg0 = funcgen.expr(op.args[0])
    arg1 = funcgen.expr(op.args[1])
    result = funcgen.expr(op.result)
    return '%s = stm_pointer_equal(%s, %s);' % (result, arg0, arg1)

def stm_become_inevitable(funcgen, op):
    try:
        info = op.args[0].value
    except IndexError:
        info = "rstm.become_inevitable"    # cannot insert it in 'llop'
    string_literal = c_string_constant(info)
    return 'stm_become_inevitable(%s);' % (string_literal,)

def stm_push_root(funcgen, op):
    arg0 = funcgen.expr(op.args[0])
    return 'stm_push_root((gcptr)%s);' % (arg0,)

def stm_pop_root_into(funcgen, op):
    arg0 = funcgen.expr(op.args[0])
    return '%s = (%s)stm_pop_root();' % (
        arg0, cdecl(funcgen.lltypename(op.args[0]), ''))

def stm_allocate(funcgen, op):
    arg0 = funcgen.expr(op.args[0])
    arg1 = funcgen.expr(op.args[1])
    result = funcgen.expr(op.result)
    return '%s = stm_allocate(%s, %s);' % (result, arg0, arg1)

def stm_get_tid(funcgen, op):
    arg0 = funcgen.expr(op.args[0])
    result = funcgen.expr(op.result)
    return '%s = stm_get_tid((gcptr)%s);' % (result, arg0)


def op_stm(funcgen, op):
    func = globals()[op.opname]
    return func(funcgen, op)
