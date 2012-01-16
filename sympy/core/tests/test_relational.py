from sympy.utilities.pytest import XFAIL, raises
from sympy import symbols, oo
from sympy.core.relational import Relational, Equality, StrictInequality, \
    Rel, Eq, Lt, Le, Gt, Ge, Ne

x,y,z = symbols('x,y,z')


def test_rel_ne():
    Relational(x, y, '!=')  # this used to raise


def test_rel_subs():
    e = Relational(x, y, '==')
    e = e.subs(x,z)

    assert isinstance(e, Equality)
    assert e.lhs == z
    assert e.rhs == y

    e = Relational(x, y, '<')
    e = e.subs(x,z)

    assert isinstance(e, StrictInequality)
    assert e.lhs == z
    assert e.rhs == y

    e = Eq(x,0)
    assert e.subs(x,0) == True
    assert e.subs(x,1) == False


def test_wrappers():
    e = x+x**2

    res = Relational(y, e, '==')
    assert Rel(y, x+x**2, '==') == res
    assert Eq(y, x+x**2) == res

    res = Relational(y, e, '<')
    assert Lt(y, x+x**2) == res

    res = Relational(y, e, '<=')
    assert Le(y, x+x**2) == res

    res = Relational(y, e, '>')
    assert Gt(y, x+x**2) == res

    res = Relational(y, e, '>=')
    assert Ge(y, x+x**2) == res

    res = Relational(y, e, '!=')
    assert Ne(y, x+x**2) == res

def test_Eq():

    assert Eq(x**2) == Eq(x**2, 0)
    assert Eq(x**2) != Eq(x**2, 1)

def test_rel_Infinity():
    assert (oo > oo) is False
    assert (oo > -oo) is True
    assert (oo > 1) is True
    assert (oo < oo) is False
    assert (oo < -oo) is False
    assert (oo < 1) is False
    assert (oo >= oo) is True
    assert (oo >= -oo) is True
    assert (oo >= 1) is True
    assert (oo <= oo) is True
    assert (oo <= -oo) is False
    assert (oo <= 1) is False
    assert (-oo > oo) is False
    assert (-oo > -oo) is False
    assert (-oo > 1) is False
    assert (-oo < oo) is True
    assert (-oo < -oo) is False
    assert (-oo < 1) is True
    assert (-oo >= oo) is False
    assert (-oo >= -oo) is True
    assert (-oo >= 1) is False
    assert (-oo <= oo) is True
    assert (-oo <= -oo) is True
    assert (-oo <= 1) is True

def test_bool():
    assert Eq(0,0) is True
    assert Eq(1,0) is False
    assert Ne(0,0) is False
    assert Ne(1,0) is True
    assert Lt(0,1) is True
    assert Lt(1,0) is False
    assert Le(0,1) is True
    assert Le(1,0) is False
    assert Le(0,0) is True
    assert Gt(1,0) is True
    assert Gt(0,1) is False
    assert Ge(1,0) is True
    assert Ge(0,1) is False
    assert Ge(1,1) is True

def test_rich_cmp():
    assert (x<y) == Lt(x,y)
    assert (x<=y) == Le(x,y)
    assert (x>y) == Gt(x,y)
    assert (x>=y) == Ge(x,y)

def test_doit():
    from sympy import Symbol
    p = Symbol('p', positive=True)
    n = Symbol('n', negative=True)
    np = Symbol('np', nonpositive=True)
    nn = Symbol('nn', nonnegative=True)

    assert Gt(p, 0).doit() is True
    assert Gt(p, 1).doit() == Gt(p, 1)
    assert Ge(p, 0).doit() is True
    assert Le(p, 0).doit() is False
    assert Lt(n, 0).doit() is True
    assert Le(np, 0).doit() is True
    assert Gt(nn, 0).doit() == Gt(nn, 0)
    assert Lt(nn, 0).doit() is False

    assert Eq(x, 0).doit() == Eq(x, 0)

@XFAIL
def test_relational_bool_output():
    # XFail test for issue:
    # http://code.google.com/p/sympy/issues/detail?id=2832
    raises(ValueError, "bool(x > 3)")

@XFAIL
def test_issue_2620():
    from sympy import Symbol
    x = Symbol('x')
    assert Eq(x, x) == True
    x = Symbol('x', positive=True)
    assert Ne(x, 0) == False
