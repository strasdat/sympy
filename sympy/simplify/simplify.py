from collections import defaultdict

from sympy import SYMPY_DEBUG

from sympy.core import (Basic, S, C, Add, Mul, Pow, Rational, Integer,
    Derivative, Wild, Symbol, sympify, expand, expand_mul, expand_func,
    Function, Equality, Dummy, Atom, count_ops, Expr, factor_terms,
    expand_multinomial)

from sympy.core.compatibility import iterable, reduce
from sympy.core.numbers import igcd, Float
from sympy.core.function import expand_log, count_ops
from sympy.core.mul import _keep_coeff
from sympy.core.rules import Transform

from sympy.utilities import flatten, default_sort_key
from sympy.functions import gamma, exp, sqrt, log, root, exp_polar

from sympy.simplify.cse_main import cse
from sympy.simplify.sqrtdenest import sqrtdenest

from sympy.polys import (Poly, together, reduced, cancel, factor,
    ComputationFailed, terms_gcd, lcm, gcd)
from sympy.polys.polytools import _keep_coeff

import sympy.mpmath as mpmath

def fraction(expr, exact=False):
    """Returns a pair with expression's numerator and denominator.
       If the given expression is not a fraction then this function
       will return the tuple (expr, 1).

       This function will not make any attempt to simplify nested
       fractions or to do any term rewriting at all.

       If only one of the numerator/denominator pair is needed then
       use numer(expr) or denom(expr) functions respectively.

       >>> from sympy import fraction, Rational, Symbol
       >>> from sympy.abc import x, y

       >>> fraction(x/y)
       (x, y)
       >>> fraction(x)
       (x, 1)

       >>> fraction(1/y**2)
       (1, y**2)

       >>> fraction(x*y/2)
       (x*y, 2)
       >>> fraction(Rational(1, 2))
       (1, 2)

       This function will also work fine with assumptions:

       >>> k = Symbol('k', negative=True)
       >>> fraction(x * y**k)
       (x, y**(-k))

       If we know nothing about sign of some exponent and 'exact'
       flag is unset, then structure this exponent's structure will
       be analyzed and pretty fraction will be returned:

       >>> from sympy import exp
       >>> fraction(2*x**(-y))
       (2, x**y)

       >>> fraction(exp(-x))
       (1, exp(x))

       >>> fraction(exp(-x), exact=True)
       (exp(-x), 1)

    """
    expr = sympify(expr)

    numer, denom = [], []

    for term in Mul.make_args(expr):
        if term.is_commutative and (term.is_Pow or term.func is exp):
            b, ex = term.as_base_exp()
            if ex.is_negative:
                if ex is S.NegativeOne:
                    denom.append(b)
                else:
                    denom.append(Pow(b, -ex))
            elif not exact and ex.is_Mul:
                n, d = term.as_numer_denom()
                numer.append(n)
                denom.append(d)
            else:
                numer.append(term)
        elif term.is_Rational:
            n, d = term.as_numer_denom()
            numer.append(n)
            denom.append(d)
        else:
            numer.append(term)

    return Mul(*numer), Mul(*denom)

def numer(expr):
    return fraction(expr)[0]

def denom(expr):
    return fraction(expr)[1]

def fraction_expand(expr, **hints):
    return expr.expand(frac=True, **hints)

def numer_expand(expr, **hints):
    a, b = fraction(expr)
    return a.expand(numer=True, **hints) / b

def denom_expand(expr, **hints):
    a, b = fraction(expr)
    return a / b.expand(denom=True, **hints)

expand_numer = numer_expand
expand_denom = denom_expand
expand_fraction = fraction_expand

def separate(expr, deep=False, force=False):
    """A wrapper to expand(power_base=True) which separates a power
       with a base that is a Mul into a product of powers, without performing
       any other expansions, provided that assumptions about the power's base
       and exponent allow.

       deep=True (default is False) will do separations inside functions.

       force=True (default is False) will cause the expansion to ignore
       assumptions about the base and exponent. When False, the expansion will
       only happen if the base is non-negative or the exponent is an integer.

       >>> from sympy.abc import x, y, z
       >>> from sympy import separate, sin, cos, exp

       >>> (x*y)**2
       x**2*y**2

       >>> (2*x)**y
       (2*x)**y
       >>> separate(_)
       2**y*x**y

       >>> separate((x*y)**z)
       (x*y)**z
       >>> separate((x*y)**z, force=True)
       x**z*y**z
       >>> separate(sin((x*y)**z))
       sin((x*y)**z)
       >>> separate(sin((x*y)**z), deep=True, force=True)
       sin(x**z*y**z)

       >>> separate((2*sin(x))**y + (2*cos(x))**y)
       2**y*sin(x)**y + 2**y*cos(x)**y

       >>> separate((2*exp(y))**x)
       2**x*exp(x*y)

       >>> separate((2*cos(x))**y)
       2**y*cos(x)**y

       Notice that summations are left untouched. If this is not the
       desired behavior, apply 'expand' to the expression:

       >>> separate(((x+y)*z)**2)
       z**2*(x + y)**2
       >>> (((x+y)*z)**2).expand()
       x**2*z**2 + 2*x*y*z**2 + y**2*z**2

       >>> separate((2*y)**(1+z))
       2**(z + 1)*y**(z + 1)
       >>> ((2*y)**(1+z)).expand()
       2*2**z*y*y**z

    """
    return sympify(expr).expand(deep=deep, mul=False, power_exp=False,\
    power_base=True, basic=False, multinomial=False, log=False, force=force)

def collect(expr, syms, func=None, evaluate=True, exact=False, distribute_order_term=True):
    """
    Collect additive terms of an expression.

    This function collects additive terms of an expression with respect
    to a list of expression up to powers with rational exponents. By the
    term symbol here are meant arbitrary expressions, which can contain
    powers, products, sums etc. In other words symbol is a pattern which
    will be searched for in the expression's terms.

    The input expression is not expanded by :func:`collect`, so user is
    expected to provide an expression is an appropriate form. This makes
    :func:`collect` more predictable as there is no magic happening behind
    the scenes. However, it is important to note, that powers of products
    are converted to products of powers using :func:`separate` function.

    There are two possible types of output. First, if ``evaluate`` flag is
    set, this function will return an expression with collected terms or
    else it will return a dictionary with expressions up to rational powers
    as keys and collected coefficients as values.

    Examples
    ========

    >>> from sympy import S, collect, expand, factor, Wild
    >>> from sympy.abc import a, b, c, x, y, z

    This function can collect symbolic coefficients in polynomials or
    rational expressions. It will manage to find all integer or rational
    powers of collection variable::

        >>> collect(a*x**2 + b*x**2 + a*x - b*x + c, x)
        c + x**2*(a + b) + x*(a - b)

    The same result can be achieved in dictionary form::

        >>> d = collect(a*x**2 + b*x**2 + a*x - b*x + c, x, evaluate=False)
        >>> d[x**2]
        a + b
        >>> d[x]
        a - b
        >>> d[S.One]
        c

    You can also work with multivariate polynomials. However, remember that
    this function is greedy so it will care only about a single symbol at time,
    in specification order::

        >>> collect(x**2 + y*x**2 + x*y + y + a*y, [x, y])
        x**2*(y + 1) + x*y + y*(a + 1)

    Also more complicated expressions can be used as patterns::

        >>> from sympy import sin, log
        >>> collect(a*sin(2*x) + b*sin(2*x), sin(2*x))
        (a + b)*sin(2*x)

        >>> collect(a*x*log(x) + b*(x*log(x)), x*log(x))
        x*(a + b)*log(x)

    You can use wildcards in the pattern::

        >>> w = Wild('w1')
        >>> collect(a*x**y - b*x**y, w**y)
        x**y*(a - b)

    It is also possible to work with symbolic powers, although it has more
    complicated behavior, because in this case power's base and symbolic part
    of the exponent are treated as a single symbol::

        >>> collect(a*x**c + b*x**c, x)
        a*x**c + b*x**c
        >>> collect(a*x**c + b*x**c, x**c)
        x**c*(a + b)

    However if you incorporate rationals to the exponents, then you will get
    well known behavior::

        >>> collect(a*x**(2*c) + b*x**(2*c), x**c)
        (a + b)*(x**2)**c

    Note also that all previously stated facts about :func:`collect` function
    apply to the exponential function, so you can get::

        >>> from sympy import exp
        >>> collect(a*exp(2*x) + b*exp(2*x), exp(x))
        (a + b)*exp(2*x)

    If you are interested only in collecting specific powers of some symbols
    then set ``exact`` flag in arguments::

        >>> collect(a*x**7 + b*x**7, x, exact=True)
        a*x**7 + b*x**7
        >>> collect(a*x**7 + b*x**7, x**7, exact=True)
        x**7*(a + b)

    You can also apply this function to differential equations, where derivatives
    of arbitrary order can be collected. Note that if you collect with respect
    to a function or a derivative of a function, all derivatives of that function
    will also be collected. Use ``exact=True`` to prevent this from happening::

        >>> from sympy import Derivative as D, collect, Function
        >>> f = Function('f') (x)

        >>> collect(a*D(f,x) + b*D(f,x), D(f,x))
        (a + b)*Derivative(f(x), x)

        >>> collect(a*D(D(f,x),x) + b*D(D(f,x),x), f)
        (a + b)*Derivative(f(x), x, x)

        >>> collect(a*D(D(f,x),x) + b*D(D(f,x),x), D(f,x), exact=True)
        a*Derivative(f(x), x, x) + b*Derivative(f(x), x, x)

        >>> collect(a*D(f,x) + b*D(f,x) + a*f + b*f, f)
        (a + b)*f(x) + (a + b)*Derivative(f(x), x)

    Or you can even match both derivative order and exponent at the same time::

        >>> collect(a*D(D(f,x),x)**2 + b*D(D(f,x),x)**2, D(f,x))
        (a + b)*Derivative(f(x), x, x)**2

    Finally, you can apply a function to each of the collected coefficients.
    For example you can factorize symbolic coefficients of polynomial::

        >>> f = expand((x + a + 1)**3)

        >>> collect(f, x, factor)
        x**3 + 3*x**2*(a + 1) + 3*x*(a + 1)**2 + (a + 1)**3

    .. note:: Arguments are expected to be in expanded form, so you might have
              to call :func:`expand` prior to calling this function.

    """
    def make_expression(terms):
        product = []

        for term, rat, sym, deriv in terms:
            if deriv is not None:
                var, order = deriv

                while order > 0:
                    term, order = Derivative(term, var), order-1

            if sym is None:
                if rat is S.One:
                    product.append(term)
                else:
                    product.append(Pow(term, rat))
            else:
                product.append(Pow(term, rat*sym))

        return Mul(*product)

    def parse_derivative(deriv):
        # scan derivatives tower in the input expression and return
        # underlying function and maximal differentiation order
        expr, sym, order = deriv.expr, deriv.variables[0], 1

        for s in deriv.variables[1:]:
            if s == sym:
                order += 1
            else:
                raise NotImplementedError('Improve MV Derivative support in collect')

        while isinstance(expr, Derivative):
            s0 = expr.variables[0]

            for s in expr.variables:
                if s != s0:
                    raise NotImplementedError('Improve MV Derivative support in collect')

            if s0 == sym:
                expr, order = expr.expr, order+len(expr.variables)
            else:
                break

        return expr, (sym, Rational(order))

    def parse_term(expr):
        """Parses expression expr and outputs tuple (sexpr, rat_expo,
        sym_expo, deriv)
        where:
         - sexpr is the base expression
         - rat_expo is the rational exponent that sexpr is raised to
         - sym_expo is the symbolic exponent that sexpr is raised to
         - deriv contains the derivatives the the expression

         for example, the output of x would be (x, 1, None, None)
         the output of 2**x would be (2, 1, x, None)
        """
        rat_expo, sym_expo = S.One, None
        sexpr, deriv = expr, None

        if expr.is_Pow:
            if isinstance(expr.base, Derivative):
                sexpr, deriv = parse_derivative(expr.base)
            else:
                sexpr = expr.base

            if expr.exp.is_Rational:
                rat_expo = expr.exp
            elif expr.exp.is_Mul:
                coeff, tail = expr.exp.as_coeff_mul()

                if coeff.is_Rational:
                    rat_expo, sym_expo = coeff, expr.exp._new_rawargs(*tail)
                else:
                    sym_expo = expr.exp
            else:
                sym_expo = expr.exp
        elif expr.func is C.exp:
            arg = expr.args[0]
            if arg.is_Rational:
                sexpr, rat_expo = S.Exp1, arg
            elif arg.is_Mul:
                coeff, tail = arg.as_coeff_mul()

                if coeff.is_Rational:
                    sexpr, rat_expo = C.exp(arg._new_rawargs(*tail)), coeff
        elif isinstance(expr, Derivative):
            sexpr, deriv = parse_derivative(expr)

        return sexpr, rat_expo, sym_expo, deriv

    def parse_expression(terms, pattern):
        """Parse terms searching for a pattern.
        terms is a list of tuples as returned by parse_terms;
        pattern is an expression treated as a product of factors
        """
        pattern = Mul.make_args(pattern)

        if len(terms) < len(pattern):
            # pattern is longer than matched product
            # so no chance for positive parsing result
            return None
        else:
            pattern = [parse_term(elem) for elem in pattern]

            terms = terms[:] # need a copy
            elems, common_expo, has_deriv = [], None, False

            for elem, e_rat, e_sym, e_ord in pattern:

                if elem.is_Number:
                    # a constant is a match for everything
                    continue

                for j in range(len(terms)):
                    if terms[j] is None:
                        continue

                    term, t_rat, t_sym, t_ord = terms[j]

                    # keeping track of whether one of the terms had
                    # a derivative or not as this will require rebuilding
                    # the expression later
                    if t_ord is not None:
                        has_deriv= True

                    if (term.match(elem) is not None and \
                            (t_sym == e_sym or t_sym is not None and \
                            e_sym is not None and \
                            t_sym.match(e_sym) is not None)):
                        if exact == False:
                            # we don't have to be exact so find common exponent
                            # for both expression's term and pattern's element
                            expo = t_rat / e_rat

                            if common_expo is None:
                                # first time
                                common_expo = expo
                            else:
                                # common exponent was negotiated before so
                                # there is no chance for a pattern match unless
                                # common and current exponents are equal
                                if common_expo != expo:
                                    common_expo = 1
                        else:
                            # we ought to be exact so all fields of
                            # interest must match in every details
                            if e_rat != t_rat or e_ord != t_ord:
                                continue

                        # found common term so remove it from the expression
                        # and try to match next element in the pattern
                        elems.append(terms[j])
                        terms[j] = None

                        break

                else:
                    # pattern element not found
                    return None

            return filter(None, terms), elems, common_expo, has_deriv

    if evaluate:
        if expr.is_Mul:
            return Mul(*[ collect(term, syms, func, True, exact, distribute_order_term) for term in expr.args ])
        elif expr.is_Pow:
            b = collect(expr.base, syms, func, True, exact, distribute_order_term)
            return Pow(b, expr.exp)

    if hasattr(syms, '__iter__') or hasattr(syms, '__getitem__'):
        syms = map(separate, syms)
    else:
        syms = [ separate(syms) ]

    expr = sympify(expr)
    order_term = None

    if distribute_order_term:
        order_term = expr.getO()

        if order_term is not None:
            if order_term.has(*syms):
                order_term = None
            else:
                expr = expr.removeO()

    summa = map(separate, Add.make_args(expr))

    collected, disliked = defaultdict(lambda: S.Zero), S.Zero
    for product in summa:
        terms = [parse_term(i) for i in Mul.make_args(product)]

        for symbol in syms:
            if SYMPY_DEBUG:
                print "DEBUG: parsing of expression %s with symbol %s " % (str(terms), str(symbol))

            result = parse_expression(terms, symbol)

            if SYMPY_DEBUG:
                print "DEBUG: returned %s" %  str(result)

            if result is not None:
                terms, elems, common_expo, has_deriv = result

                # when there was derivative in current pattern we
                # will need to rebuild its expression from scratch
                if not has_deriv:
                    index = 1
                    for elem in elems:
                        index *= Pow(elem[0], elem[1])
                        if elem[2] is not None:
                            index **= elem[2]
                else:
                    index = make_expression(elems)
                terms = separate(make_expression(terms))
                index = separate(index)
                collected[index] += terms
                break
        else:
            # none of the patterns matched
            disliked += product

    if disliked is not S.Zero:
        collected[S.One] = disliked

    if order_term is not None:
        for key, val in collected.iteritems():
            collected[key] = val + order_term

    if func is not None:
        collected = dict([ (key, func(val)) for key, val in collected.iteritems() ])

    if evaluate:
        return Add(*[key*val for key, val in collected.iteritems()])
    else:
        return collected

def rcollect(expr, *vars):
    """
    Recursively collect sums in an expression.

    Examples
    ========

    >>> from sympy.simplify import rcollect
    >>> from sympy.abc import x, y

    >>> expr = (x**2*y + x*y + x + y)/(x + y)

    >>> rcollect(expr, y)
    (x + y*(x**2 + x + 1))/(x + y)

    """
    if expr.is_Atom or not expr.has(*vars):
        return expr
    else:
        expr = expr.__class__(*[ rcollect(arg, *vars) for arg in expr.args ])

        if expr.is_Add:
            return collect(expr, vars)
        else:
            return expr

def separatevars(expr, symbols=[], dict=False, force=False):
    """
    Separates variables in an expression, if possible.  By
    default, it separates with respect to all symbols in an
    expression and collects constant coefficients that are
    independent of symbols.

    If dict=True then the separated terms will be returned
    in a dictionary keyed to their corresponding symbols.
    By default, all symbols in the expression will appear as
    keys; if symbols are provided, then all those symbols will
    be used as keys, and any terms in the expression containing
    other symbols or non-symbols will be returned keyed to the
    string 'coeff'. (Passing None for symbols will return the
    expression in a dictionary keyed to 'coeff'.)

    If force=True, then power bases will only be separated if assumptions
    allow.

    Note: the order of the factors is determined by Mul, so that the
    separated expressions may not necessarily be grouped together.

    Examples
    ========

    >>> from sympy.abc import x, y, z, alpha
    >>> from sympy import separatevars, sin
    >>> separatevars((x*y)**y)
    (x*y)**y
    >>> separatevars((x*y)**y, force=True)
    x**y*y**y
    >>> separatevars(2*x**2*z*sin(y)+2*z*x**2)
    2*x**2*z*(sin(y) + 1)

    >>> separatevars(2*x+y*sin(x))
    2*x + y*sin(x)
    >>> separatevars(2*x**2*z*sin(y)+2*z*x**2, symbols=(x, y), dict=True)
    {'coeff': 2*z, x: x**2, y: sin(y) + 1}
    >>> separatevars(2*x**2*z*sin(y)+2*z*x**2, [x, y, alpha], dict=True)
    {'coeff': 2*z, alpha: 1, x: x**2, y: sin(y) + 1}

    If the expression is not really separable, or is only partially
    separable, separatevars will do the best it can to separate it.

    >>> separatevars(x+x*y-3*(x**2))
    -x*(3*x - y - 1)

    If the expression is not separable then expr is returned unchanged
    or (if dict=True) then None is returned.

    >>> eq = 2*x+y*sin(x)
    >>> separatevars(eq) == eq
    True
    >>> separatevars(2*x+y*sin(x), symbols=(x, y), dict=True) == None
    True

    """

    if dict:
        return _separatevars_dict(_separatevars(expr, force), symbols)
    else:
        return _separatevars(expr, force)

def _separatevars(expr, force):
    # get a Pow ready for expansion
    if expr.is_Pow:
        expr = Pow(separatevars(expr.base, force=force), expr.exp)

    # First try other expansion methods
    expr = expr.expand(mul=False, multinomial=False, force=force)

    _expr = expr.expand(power_exp=False, deep=False, force=force)

    if not force:
        # factor will expand bases so we mask them off now
        pows = [p for p in _expr.atoms(Pow) if p.base.is_Mul]
        dums = [Dummy(str(i)) for i in xrange(len(pows))]
        _expr = _expr.subs(dict(zip(pows, dums)))

    _expr = factor(_expr, expand=False)

    if not force:
        # and retore them
        _expr = _expr.subs(dict(zip(dums, pows)))



    if not _expr.is_Add:
        expr = _expr

    if expr.is_Add:

        nonsepar = sympify(0)
        # Find any common coefficients to pull out
        commoncsetlist = []
        for i in expr.args:
            if i.is_Mul:
                commoncsetlist.append(set(i.args))
            else:
                commoncsetlist.append(set((i,)))
        commoncset = set(flatten(commoncsetlist))
        commonc = sympify(1)

        for i in commoncsetlist:
            commoncset = commoncset.intersection(i)
        commonc = Mul(*commoncset)

        for i in expr.args:
            coe = i.extract_multiplicatively(commonc)
            if coe == None:
                nonsepar += sympify(1)
            else:
                nonsepar += coe
        if nonsepar == 0:
            return commonc
        else:
            return commonc*nonsepar

    else:
        return expr

def _separatevars_dict(expr, symbols):
    if symbols:
        assert all((t.is_Atom for t in symbols)), "symbols must be Atoms."
        symbols = list(symbols)
    elif symbols is None:
        return {'coeff': expr}
    else:
        symbols = list(expr.free_symbols)
        if not symbols:
            return None

    ret = dict(((i, S.One) for i in symbols + ['coeff']))

    for i in Mul.make_args(expr):
        expsym = i.free_symbols
        intersection = set(symbols).intersection(expsym)
        if len(intersection) > 1:
            return None
        if len(intersection) == 0:
            # There are no symbols, so it is part of the coefficient
            ret['coeff'] *= i
        else:
            ret[intersection.pop()] *= i

    return ret

def ratsimp(expr):
    """
    Put an expression over a common denominator, cancel and reduce.

    Examples
    ========

    >>> from sympy import ratsimp
    >>> from sympy.abc import x, y
    >>> ratsimp(1/x + 1/y)
    (x + y)/(x*y)
    """

    f, g = cancel(expr).as_numer_denom()
    try:
        Q, r = reduced(f, [g], field=True, expand=False)
    except ComputationFailed:
        return f/g

    return Add(*Q) + cancel(r/g)

def trigsimp(expr, deep=False, recursive=False):
    """
    reduces expression by using known trig identities

    Notes
    =====

    deep:
    - Apply trigsimp inside functions

    recursive:
    - Use common subexpression elimination (cse()) and apply
    trigsimp recursively (recursively==True is quite expensive
    operation if the expression is large)

    Examples
    ========

    >>> from sympy import trigsimp, sin, cos, log
    >>> from sympy.abc import x, y
    >>> e = 2*sin(x)**2 + 2*cos(x)**2
    >>> trigsimp(e)
    2
    >>> trigsimp(log(e))
    log(2*sin(x)**2 + 2*cos(x)**2)
    >>> trigsimp(log(e), deep=True)
    log(2)

    """
    sin, cos, tan, cot = C.sin, C.cos, C.tan, C.cot
    if not expr.has(sin, cos, tan, cot):
        return expr

    if recursive:
        w, g = cse(expr)
        g = trigsimp_nonrecursive(g[0])

        for sub in reversed(w):
            g = g.subs(sub[0], sub[1])
            g = trigsimp_nonrecursive(g)
        result = g
    else:
        result = trigsimp_nonrecursive(expr, deep)

    return result


def trigsimp_nonrecursive(expr, deep=False):
    """
    A nonrecursive trig simplifier, used from trigsimp. Reduces expression by
    using known trig identities

    Notes
    =====

    deep -> apply trigsimp inside functions

    Examples
    ========

    >>> from sympy import cos, sin, log
    >>> from sympy.simplify.simplify import trigsimp, trigsimp_nonrecursive
    >>> from sympy.abc import x, y
    >>> e = 2*sin(x)**2 + 2*cos(x)**2
    >>> trigsimp(e)
    2
    >>> trigsimp_nonrecursive(log(e))
    log(2*sin(x)**2 + 2*cos(x)**2)
    >>> trigsimp_nonrecursive(log(e), deep=True)
    log(2)

    """
    sin, cos, tan, cot = C.sin, C.cos, C.tan, C.cot

    if expr.is_Function:
        if deep:
            return expr.func(trigsimp_nonrecursive(expr.args[0], deep))
    elif expr.is_Mul:
        # do some simplifications like sin/cos -> tan:
        a,b,c = map(Wild, 'abc')
        matchers = (
                (a*sin(b)**c/cos(b)**c, a*tan(b)**c),
                (a*tan(b)**c*cos(b)**c, a*sin(b)**c),
                (a*cot(b)**c*sin(b)**c, a*cos(b)**c),
                (a*tan(b)**c/sin(b)**c, a/cos(b)**c),
                (a*cot(b)**c/cos(b)**c, a/sin(b)**c),
        )
        for pattern, simp in matchers:
            res = expr.match(pattern)
            if res is not None:
                # if c is missing or zero, do nothing:
                if (not c in res) or res[c] == 0:
                    continue
                # if "a" contains any of sin("b"), cos("b"), tan("b") or cot("b),
                # skip the simplification:
                if res[a].has(cos(res[b]), sin(res[b]), tan(res[b]), cot(res[b])):
                    continue
                # simplify and finish:
                expr = simp.subs(res)
                break
        if not expr.is_Mul:
            return trigsimp_nonrecursive(expr, deep)
        ret = S.One
        for x in expr.args:
            ret *= trigsimp_nonrecursive(x, deep)
        return ret
    elif expr.is_Pow:
        return Pow(trigsimp_nonrecursive(expr.base, deep),
                trigsimp_nonrecursive(expr.exp, deep))
    elif expr.is_Add:
        # TODO this needs to be faster

        # The types of trig functions we are looking for
        a,b,c = map(Wild, 'abc')
        matchers = (
            (a*sin(b)**2, a - a*cos(b)**2),
            (a*tan(b)**2, a*(1/cos(b))**2 - a),
            (a*cot(b)**2, a*(1/sin(b))**2 - a)
        )

        # Scan for the terms we need
        ret = S.Zero
        for term in expr.args:
            term = trigsimp_nonrecursive(term, deep)
            res = None
            for pattern, result in matchers:
                res = term.match(pattern)
                if res is not None:
                    ret += result.subs(res)
                    break
            if res is None:
                ret += term

        # Reduce any lingering artifacts, such as sin(x)**2 changing
        # to 1-cos(x)**2 when sin(x)**2 was "simpler"
        artifacts = (
            (a - a*cos(b)**2 + c, a*sin(b)**2 + c, cos),
            (a - a*(1/cos(b))**2 + c, -a*tan(b)**2 + c, cos),
            (a - a*(1/sin(b))**2 + c, -a*cot(b)**2 + c, sin)
        )

        expr = ret
        for pattern, result, ex in artifacts:
            # Substitute a new wild that excludes some function(s)
            # to help influence a better match. This is because
            # sometimes, for example, 'a' would match sec(x)**2
            a_t = Wild('a', exclude=[ex])
            pattern = pattern.subs(a, a_t)
            result = result.subs(a, a_t)
            if expr.is_number:
                continue

            m = expr.match(pattern)
            while m is not None:
                if m[a_t] == 0 or -m[a_t] in m[c].args or m[a_t] + m[c] == 0:
                    break
                expr = result.subs(m)
                m = expr.match(pattern)

        return expr
    return expr

def collect_sqrt(expr, evaluate=True):
    """Return expr with terms having common square roots collected together.
    If ``evaluate`` is False a count indicating the number of sqrt-containing
    terms will be returned and the returned expression will be an unevaluated
    Add with args ordered by default_sort_key.

    Note: since I = sqrt(-1), it is collected, too.

    Examples
    ========

    >>> from sympy import sqrt
    >>> from sympy.simplify.simplify import collect_sqrt
    >>> from sympy.abc import a, b

    >>> r2, r3, r5 = [sqrt(i) for i in [2, 3, 5]]
    >>> collect_sqrt(a*r2 + b*r2)
    sqrt(2)*(a + b)
    >>> collect_sqrt(a*r2 + b*r2 + a*r3 + b*r3)
    sqrt(2)*(a + b) + sqrt(3)*(a + b)
    >>> collect_sqrt(a*r2 + b*r2 + a*r3 + b*r5)
    sqrt(3)*a + sqrt(5)*b + sqrt(2)*(a + b)

    If evaluate is False then the arguments will be sorted and
    returned as a list and a count of the number of sqrt-containing
    terms will be returned:

    >>> collect_sqrt(a*r2 + b*r2 + a*r3 + b*r5, evaluate=False)
    ((sqrt(2)*(a + b), sqrt(3)*a, sqrt(5)*b), 3)
    >>> collect_sqrt(a*sqrt(2) + b, evaluate=False)
    ((b, sqrt(2)*a), 1)
    >>> collect_sqrt(a + b, evaluate=False)
    ((a + b,), 0)

    """
    coeff, expr = expr.as_content_primitive()
    vars = set()
    for a in Add.make_args(expr):
        for m in a.args_cnc()[0]:
            if m.is_number and (m.is_Pow and m.exp.is_Rational and m.exp.q == 2 or \
                m is S.ImaginaryUnit):
                vars.add(m)
    vars = list(vars)
    if not evaluate:
        vars.sort(key=default_sort_key)
        vars.reverse() # since it will be reversed below
    vars.sort(key=count_ops)
    vars.reverse()
    d = collect_const(expr, *vars, **dict(first=False))
    hit = expr != d
    d *= coeff

    if not evaluate:
        nrad = 0
        args = list(Add.make_args(d))
        for m in args:
            c, nc = m.args_cnc()
            for ci in c:
                if ci.is_Pow and ci.exp.is_Rational and ci.exp.q == 2 or \
                   ci is S.ImaginaryUnit:
                    nrad += 1
                    break
        if hit or nrad:
            args.sort(key=default_sort_key)
        else:
            args = [Add(*args)]
        return tuple(args), nrad

    return d

def collect_const(expr, *vars, **first):
    """A non-greedy collection of terms with similar number coefficients in
    an Add expr. If ``vars`` is given then only those constants will be
    targeted.

    Examples
    ========

    >>> from sympy import sqrt
    >>> from sympy.abc import a, s
    >>> from sympy.simplify.simplify import collect_const
    >>> collect_const(sqrt(3) + sqrt(3)*(1 + sqrt(2)))
    sqrt(3)*(sqrt(2) + 2)
    >>> collect_const(sqrt(3)*s + sqrt(7)*s + sqrt(3) + sqrt(7))
    (sqrt(3) + sqrt(7))*(s + 1)
    >>> s = sqrt(2) + 2
    >>> collect_const(sqrt(3)*s + sqrt(3) + sqrt(7)*s + sqrt(7))
    (sqrt(2) + 3)*(sqrt(3) + sqrt(7))
    >>> collect_const(sqrt(3)*s + sqrt(3) + sqrt(7)*s + sqrt(7), sqrt(3))
    sqrt(7) + sqrt(3)*(sqrt(2) + 3) + sqrt(7)*(sqrt(2) + 2)

    If no constants are provided then a leading Rational might be returned:

    >>> collect_const(2*sqrt(3) + 4*a*sqrt(5))
    2*(2*sqrt(5)*a + sqrt(3))
    >>> collect_const(2*sqrt(3) + 4*a*sqrt(5), sqrt(3))
    4*sqrt(5)*a + 2*sqrt(3)
    """

    if first.get('first', True):
        c, p = sympify(expr).as_content_primitive()
    else:
        c, p = S.One, expr
    if c is not S.One:
        if not vars:
            return _keep_coeff(c, collect_const(p, *vars, **dict(first=False)))
        # else don't leave the Rational on the outside
        return c*collect_const(p, *vars, **dict(first=False))

    if not (expr.is_Add or expr.is_Mul):
        return expr
    recurse = False
    if not vars:
        recurse = True
        vars = set()
        for a in Add.make_args(expr):
            for m in Mul.make_args(a):
                if m.is_number:
                    vars.add(m)
        vars = sorted(vars, key=count_ops)
    # Rationals get autodistributed on Add so don't bother with them
    vars = [v for v in vars if not v.is_Rational]

    if not vars:
        return expr

    for v in vars:
        terms = defaultdict(list)
        for m in Add.make_args(expr):
            i = []
            d = []
            for a in Mul.make_args(m):
                if a == v:
                    d.append(a)
                else:
                    i.append(a)
            ai, ad = [Mul(*w) for w in [i, d]]
            terms[ad].append(ai)
        args = []
        hit = False
        for k, v in terms.iteritems():
            if len(v) > 1:
                v = Add(*v)
                hit = True
                if recurse and v != expr:
                    vars.append(v)
            else:
                v = v[0]
            args.append(k*v)
        if hit:
            expr = Add(*args)
            if not expr.is_Add:
                break
    return expr

def radsimp(expr, symbolic=True):
    """
    Rationalize the denominator by removing square roots. If there are more
    than 3 terms (after collecting common square root terms) that have
    square roots then the removal is in general only partial.

    Note: the expression returned from radsimp must be used with caution
    since if the denominator contains symbols, it will be possible to make
    substitutions that violate the assumptions of the simplification process:
    that for a denominator matching a + b*sqrt(c), a != +/-b*sqrt(c). (If
    there are no symbols, this assumptions is made valid by collecting terms
    of sqrt(c) so the match variable ``a`` does not contain ``sqrt(c)``.) If
    you do not want the simplification to occur for symbolic denominators, set
    ``symbolic`` to False.


    Examples
    ========

    >>> from sympy import radsimp, sqrt, Symbol, denom, pprint, I
    >>> from sympy.abc import a, b, c

    >>> radsimp(1/(I + 1))
    (1 - I)/2
    >>> radsimp(1/(2 + sqrt(2)))
    (-sqrt(2) + 2)/2
    >>> x,y = map(Symbol, 'xy')
    >>> e = ((2 + 2*sqrt(2))*x + (2 + sqrt(8))*y)/(2 + sqrt(2))
    >>> radsimp(e)
    sqrt(2)*(x + y)

    Terms are collected automatically:

    >>> r2 = sqrt(2)
    >>> r5 = sqrt(5)
    >>> pprint(radsimp(1/(y*r2 + x*r2 + a*r5 + b*r5)))
             ___              ___
           \/ 5 *(-a - b) + \/ 2 *(x + y)
    --------------------------------------------
         2               2      2              2
    - 5*a  - 10*a*b - 5*b  + 2*x  + 4*x*y + 2*y

    If radicals in the denominator cannot be removed, the original expression
    will be returned. If the denominator was 1 then any square roots will also
    be collected:

    >>> radsimp(sqrt(2)*x + sqrt(2))
    sqrt(2)*(x + 1)

    Results with symbols will not always be valid for all substitutions:

    >>> eq = 1/(a + b*sqrt(c))
    >>> eq.subs(a, b*sqrt(c))
    1/(2*b*sqrt(c))
    >>> radsimp(eq).subs(a, b*sqrt(c))
    nan

    If symbolic=False, symbolic denominators will not be transformed (but
    numeric denominators will still be processed):

    >>> radsimp(eq, symbolic=False)
    1/(a + b*sqrt(c))
    """

    def handle(expr):
        if expr.is_Atom or not symbolic and expr.free_symbols:
            return expr
        n, d = fraction(expr)
        if d is S.One:
            nexpr = expr.func(*[handle(ai) for ai in expr.args])
            return nexpr
        elif d.is_Mul:
            nargs = []
            dargs = []
            for di in d.args:
                ni, di = fraction(handle(1/di))
                nargs.append(ni)
                dargs.append(di)
            return n*Mul(*nargs)/Mul(*dargs)
        elif d.is_Add:
            d = radsimp(d)
        elif d.is_Pow and d.exp.is_Rational and d.exp.q == 2:
            d = sqrtdenest(sqrt(d.base))**d.exp.p

        changed = False
        nterms4 = False
        while 1:
            # collect similar terms
            d, nterms = collect_sqrt(expand_mul(expand_multinomial(d)), evaluate=False)
            d = Add._from_args(d)

            # check to see if we are done:
            # - no radical terms
            # - don't continue if there are more than 4 radical
            #   terms and a constant term, too; in the case of 4 radical
            #   terms don't continue if they do not reduce after an
            #   iteration
            if not nterms:
                break
            elif nterms > 4 or nterms4 and nterms == 4 and len(d.args) > 5:
                n, d = fraction(expr)
                break
            changed = True

            # now match for a radical
            if nterms == 4 and len(d.args) == 5:
                r = d.match(a + b*sqrt(c) + D*sqrt(E) + F*sqrt(G))
                va, vb, vc, vd, ve, vf, vg = \
                    r[a], r[b], r[c], r[D], r[E], r[F], r[G]
                nmul = va - vb*sqrt(vc) - vd*sqrt(ve) - vf*sqrt(vg)
                d = va**2 - vc*vb**2 - ve*vd**2 - vg*vf**2 - \
                2*vb*vd*sqrt(vc*ve) - 2*vb*vf*sqrt(vc*vg) - 2*vd*vf*sqrt(ve*vg)
                nterms4 = True
                n1 = n/d
                if denom(n1) is not S.One:
                    n = -(-n/d)
                else:
                    n = n1
                n, d = fraction(n*nmul)

            if len(d.args) == 4:
                r = d.match(a + b*sqrt(c) + D*sqrt(E))
                va, vb, vc, vd, ve = r[a], r[b], r[c], r[D], r[E]
                nmul = va - vb*sqrt(vc) - vd*sqrt(ve)
                d = va**2 - vc*vb**2 - ve*vd**2 - 2*vb*vd*sqrt(vc*ve)
                n1 = n/d
                if denom(n1) is not S.One:
                    n = -(-n/d)
                else:
                    n = n1
                n, d = fraction(n*nmul)

            else:
                r = d.match(a + b*sqrt(c))
                if not r or r[b] == 0:
                    r = d.match(b*sqrt(c))
                    if r is None:
                        break
                    r[a] = S.Zero
                va, vb, vc = r[a],r[b],r[c]

                nmul = va - vb*sqrt(vc)
                d = va**2 - vc*vb**2
                n1 = n/d
                if denom(n1) is not S.One:
                    n = -(-n/d)
                else:
                    n = n1
                n, d = fraction(n*nmul)

        nexpr = collect_sqrt(expand_mul(n))/d
        if changed or nexpr != expr:
            expr = nexpr
        return expr

    a, b, c, D, E, F, G = map(Wild, 'abcDEFG')
    # do this at the start in case no other change is made since
    # it is done if a change is made
    coeff, expr = expr.as_content_primitive()

    newe = handle(expr)
    if newe != expr:
        co, expr = newe.as_content_primitive()
        coeff *= co
    else:
        nexpr, hit = collect_sqrt(expand_mul(expr), evaluate=False)
        nexpr = Add._from_args(nexpr)
        if hit and expr.count_ops() >= nexpr.count_ops():
            expr = Add(*Add.make_args(nexpr))
    return _keep_coeff(coeff, expr)

def posify(eq):
    """Return eq (with generic symbols made positive) and a restore
    dictionary.

    Any symbol that has positive=None will be replaced with a positive dummy
    symbol having the same name. This replacement will allow more symbolic
    processing of expressions, especially those involving powers and
    logarithms.

    A dictionary that can be sent to subs to restore eq to its original
    symbols is also returned.

    >>> from sympy import posify, Symbol, log
    >>> from sympy.abc import x
    >>> posify(x + Symbol('p', positive=True) + Symbol('n', negative=True))
    (_x + n + p, {_x: x})

    >> log(1/x).expand() # should be log(1/x) but it comes back as -log(x)
    log(1/x)

    >>> log(posify(1/x)[0]).expand() # take [0] and ignore replacements
    -log(_x)
    >>> eq, rep = posify(1/x)
    >>> log(eq).expand().subs(rep)
    -log(x)
    >>> posify([x, 1 + x])
    ([_x, _x + 1], {_x: x})
    """
    eq = sympify(eq)
    if iterable(eq):
        f = type(eq)
        eq = list(eq)
        syms = set()
        for e in eq:
            syms = syms.union(e.atoms(C.Symbol))
        reps = {}
        for s in syms:
            reps.update(dict((v, k) for k, v in posify(s)[1].items()))
        for i, e in enumerate(eq):
            eq[i] = e.subs(reps)
        return f(eq), dict([(r,s) for s, r in reps.iteritems()])

    reps = dict([(s, Dummy(s.name, positive=True))
                 for s in eq.atoms(Symbol) if s.is_positive is None])
    eq = eq.subs(reps)
    return eq, dict([(r,s) for s, r in reps.iteritems()])

def _polarify(eq, lift, pause=False):
    from sympy import polar_lift
    if eq.is_polar:
        return eq
    if eq.is_number and not pause:
        return polar_lift(eq)
    if isinstance(eq, Symbol) and not pause and lift:
        return polar_lift(eq)
    elif eq.is_Atom:
        return eq
    elif eq.is_Add:
        r = eq.func(*[_polarify(arg, lift, pause=True) for arg in eq.args])
        if lift:
            return polar_lift(r)
        return r
    elif eq.is_Function:
        return eq.func(*[_polarify(arg, lift, pause=False) for arg in eq.args])
    else:
        return eq.func(*[_polarify(arg, lift, pause=pause) for arg in eq.args])

def polarify(eq, subs=True, lift=False):
    """
    Turn all numbers in eq into their polar equivalents (under the standard
    choice of argument).

    Note that no attempt is made to guess a formal convention of adding
    polar numbers, expressions like 1 + x will generally not be altered.

    Note also that this function does not promote exp(x) to exp_polar(x).

    If `subs` is True, all symbols which are not already polar will be
    substituted for polar dummies; in this case the function behaves much
    like posify.

    If `lift` is True, both addition statements and non-polar symbols are
    changed to their polar_lift()ed versions.
    Note that lift=True implies subs=False.

    >>> from sympy import polarify, sin, I
    >>> from sympy.abc import x, y
    >>> expr = (-x)**y
    >>> expr.expand()
    (-x)**y
    >>> polarify(expr)
    ((_x*exp_polar(I*pi))**_y, {_x: x, _y: y})
    >>> polarify(expr)[0].expand()
    _x**_y*exp_polar(_y*I*pi)
    >>> polarify(x, lift=True)
    polar_lift(x)
    >>> polarify(x*(1+y), lift=True)
    polar_lift(x)*polar_lift(y + 1)

    Adds are treated carefully:

    >>> polarify(1 + sin((1 + I)*x))
    (sin(_x*polar_lift(1 + I)) + 1, {_x: x})
    """
    if lift:
        subs = False
    eq = _polarify(sympify(eq), lift)
    if not subs:
        return eq
    reps = dict([(s, Dummy(s.name, polar=True)) for s in eq.atoms(Symbol)])
    eq = eq.subs(reps)
    return eq, dict([(r,s) for s, r in reps.iteritems()])

def _unpolarify(eq, exponents_only, pause=False):
    from sympy import polar_lift, exp, principal_branch, pi

    if isinstance(eq, bool) or eq.is_Atom:
        return eq

    if eq.is_Pow:
        expo = _unpolarify(eq.exp, exponents_only)
        base = _unpolarify(eq.base, exponents_only, not (expo.is_integer and not pause))
        return base**expo

    if eq.func is exp_polar and not pause:
        return exp(_unpolarify(eq.args[0], exponents_only))
    if eq.is_Function and getattr(eq.func, 'unbranched', False):
        return eq.func(*[_unpolarify(x, exponents_only, exponents_only) for x in eq.args])
    if eq.func is principal_branch and eq.args[1] == 2*pi and not pause:
        return _unpolarify(eq.args[0], exponents_only)

    if (eq.is_Add or eq.is_Mul or eq.is_Boolean or \
        (eq.is_Relational and eq.rel_op in ('==', '!=') \
         and (eq.lhs == 0 or eq.rhs == 0)) or \
        (eq.is_Relational and not eq.rel_op in ('==', '!='))) \
       and not pause:
        return eq.func(*[_unpolarify(x, exponents_only) for x in eq.args])
    if eq.func is polar_lift and not pause:
        return _unpolarify(eq.args[0], exponents_only)
    return eq.func(*[_unpolarify(x, exponents_only, True) for x in eq.args])

def unpolarify(eq, subs={}, exponents_only=False):
    """
    If p denotes the projection from the riemann surface of the logarithm to
    the complex line, return a simplified version eq' of `eq` such that
    p(eq') == p(eq).
    Also apply the substitution subs in the end. (This is a convenience, since
    ``unpolarify`` in a certain sense undoes polarify.)

    >>> from sympy import unpolarify, polar_lift, sin, I
    >>> unpolarify(polar_lift(I + 2))
    2 + I
    >>> unpolarify(sin(polar_lift(I + 7)))
    sin(7 + I)
    """
    from sympy import exp_polar, polar_lift
    if isinstance(eq, bool):
        return eq

    eq = sympify(eq)
    if subs != {}:
        return unpolarify(eq.subs(subs))
    changed = True
    pause = False
    if exponents_only:
        pause = True
    while changed:
        changed = False
        res = _unpolarify(eq, exponents_only, pause)
        if res != eq:
            changed = True
            eq = res
        if isinstance(res, bool):
            return res
    # Finally, replacing Exp(0) by 1 is always correct.
    # So is polar_lift(0) -> 0.
    return res.subs({exp_polar(0): 1, polar_lift(0): 0})

def _denest_pow(eq):
    """
    Denest powers.

    This is a helper function for powdenest that performs the actual
    transformation.
    """
    b, e = eq.as_base_exp()

    # denest exp with log terms in exponent
    if b is S.Exp1 and e.is_Mul:
        logs = []
        other = []
        for ei in Mul.make_args(e):
            if any(aj.func is C.log for a in Mul.make_args(ei)
                    for ai in Add.make_args(a) for aj in Mul.make_args(ai)):
                logs.append(ei)
            else:
                other.append(ei)
        logs = logcombine(Mul(*logs))
        return Pow(exp(logs), Mul(*other))

    _, be = b.as_base_exp()
    if be is S.One and not (b.is_Mul or
                            b.is_Rational and b.q != 1 or
                            b.is_positive):
        return eq

    # denest eq which is either pos**e or Pow**e or Mul**e or Mul(b1**e1, b2**e2)

    # see if there is a positive, non-Mul base at the very bottom
    exponents = []
    kernel = eq
    while kernel.is_Pow:
        kernel, ex = kernel.as_base_exp()
        exponents.append(ex)
    if kernel.is_positive:
        e = Mul(*exponents)
        if kernel.is_Mul:
            b = kernel
        else:
            if kernel.is_Integer:
                # use log to see if there is a power here
                logkernel = log(kernel)
                if logkernel.is_Mul:
                    c, logk = logkernel.args
                    e *= c
                    kernel = logk.args[0]
            return Pow(kernel, e)

    # if any factor is an atom then there is nothing to be done
    # but the kernel check may have created a new exponent
    if any(s.is_Atom for s in Mul.make_args(b)):
        if exponents:
            return b**e
        return eq

    # let log handle the case of the base of the argument being a mul, e.g.
    # sqrt(x**(2*i)*y**(6*i)) -> x**i*y**(3**i) if x and y are positive; we
    # will take the log, expand it, and then factor out the common powers that
    # now appear as coefficient. We do this manually since terms_gcd pulls out
    # fractions, terms_gcd(x+x*y/2) -> x*(y + 2)/2 and we don't want the 1/2;
    # gcd won't pull out numerators from a fraction: gcd(3*x, 9*x/2) -> x but
    # we want 3*x. Neither work with noncommutatives.
    def nc_gcd(aa, bb):
        a, b = [i.as_coeff_Mul() for i in [aa, bb]]
        c = gcd(a[0], b[0]).as_numer_denom()[0]
        g = Mul(*(a[1].args_cnc(cset=True)[0] & b[1].args_cnc(cset=True)[0]))
        return _keep_coeff(c, g)

    glogb = expand_log(log(b))
    if glogb.is_Add:
        args = glogb.args
        g = reduce(nc_gcd, args)
        if g != 1:
            cg, rg = g.as_coeff_Mul()
            glogb = _keep_coeff(cg, rg*Add(*[a/g for a in args]))

    # now put the log back together again
    if glogb.func is C.log or not glogb.is_Mul:
        if glogb.args[0].is_Pow or glogb.args[0].func is exp:
            glogb = _denest_pow(glogb.args[0])
            c, _ = glogb.exp.as_coeff_mul()
            ok = c.p != 1
            if ok:
                ok = c.q != 1
                if not ok:
                    n, d = glogb.exp.as_numer_denom()
                    ok = d is not S.One and any(di.is_integer for di in Mul.make_args(d))
            if ok:
                return Pow(Pow(glogb.base, glogb.exp/c.p), c.p*e)
        return eq
    # the log(b) was a Mul so join any adds with logcombine
    add= []
    other = []
    for a in glogb.args:
        if a.is_Add:
            add.append(a)
        else:
            other.append(a)
    return Pow(exp(logcombine(Mul(*add))), e*Mul(*other))

def powdenest(eq, force=False, polar=False):
    r"""
    Collect exponents on powers as assumptions allow.

    Given (bb**be)**e, this can be simplified as follows:

    - if bb is positive or e is an integer, bb**(be*e)
    - if be has an integer in the denominator, then
      all integers from its numerator can be joined with e

    Given a product of powers raised to a power, (bb1**be1 * bb2**be2...)**e,
    simplification can be done as follows:

    - if e is positive, the gcd of all bei can be joined with e;
    - all non-negative bb can be separated from those that are negative
      and their gcd can be joined with e; autosimplification already
      handles this separation.
    - integer factors from powers that have integers in the denominator
      of the exponent can be removed from any term and the gcd of such
      integers can be joined with e

    Setting ``force`` to True will make symbols that are not explicitly
    negative behave as though they are positive, resulting in more
    denesting.

    Setting `polar` to True will do simplifications on the riemann surface of
    the logarithm, also resulting in more denestings.

    When there are sums of logs in exp() then a product of powers may be
    obtained e.g. exp(3*(log(a) + 2*log(b))) - > a**3*b**6.

    Examples
    ========

    >>> from sympy.abc import a, b, x, y, z
    >>> from sympy import Symbol, exp, log, sqrt, symbols, powdenest

    >>> powdenest((x**(2*a/3))**(3*x))
    (x**(a/3))**(6*x)
    >>> powdenest(exp(3*x*log(2)))
    2**(3*x)

    Assumptions may prevent expansion:

    >>> powdenest(sqrt(x**2))
    sqrt(x**2)

    >>> p = symbols('p', positive=True)
    >>> powdenest(sqrt(p**2))
    p

    No other expansion is done.

    >>> i, j = symbols('i,j', integer=True)
    >>> powdenest((x**x)**(i + j)) # -X-> (x**x)**i*(x**x)**j
    x**(x*(i + j))

    But exp() will be denested by moving all non-log terms outside of
    the function; this may result in the collapsing of the exp to a power
    with a different base:

    >>> powdenest(exp(3*y*log(x)))
    x**(3*y)
    >>> powdenest(exp(y*(log(a) + log(b))))
    (a*b)**y
    >>> powdenest(exp(3*(log(a) + log(b))))
    a**3*b**3

    If assumptions allow, symbols can also be moved to the outermost exponent:

    >>> i = Symbol('i', integer=True)
    >>> p = Symbol('p', positive=True)
    >>> powdenest(((x**(2*i))**(3*y))**x)
    ((x**(2*i))**(3*y))**x
    >>> powdenest(((x**(2*i))**(3*y))**x, force=True)
    x**(6*i*x*y)

    >>> powdenest(((p**(2*a))**(3*y))**x)
    p**(6*a*x*y)

    >>> powdenest(((x**(2*a/3))**(3*y/i))**x)
    ((x**(a/3))**(y/i))**(6*x)
    >>> powdenest((x**(2*i)*y**(4*i))**z, force=True)
    (x*y**2)**(2*i*z)

    >>> n = Symbol('n', negative=True)

    >>> powdenest((x**i)**y, force=True)
    x**(i*y)
    >>> powdenest((n**i)**x, force=True)
    (n**i)**x

    """

    if force:
        eq, rep = posify(eq)
        return powdenest(eq, force=False).xreplace(rep)

    if polar:
        eq, rep = polarify(eq)
        return unpolarify(powdenest(unpolarify(eq, exponents_only=True)), rep)

    new = powsimp(sympify(eq))
    return new.xreplace(Transform(_denest_pow, filter=lambda m: m.is_Pow or m.func is exp))

def powsimp(expr, deep=False, combine='all', force=False, measure=count_ops):
    """
    reduces expression by combining powers with similar bases and exponents.

    Notes
    =====

    If deep is True then powsimp() will also simplify arguments of
    functions. By default deep is set to False.

    If force is True then bases will be combined without checking for
    assumptions, e.g. sqrt(x)*sqrt(y) -> sqrt(x*y) which is not true
    if x and y are both negative.

    You can make powsimp() only combine bases or only combine exponents by
    changing combine='base' or combine='exp'.  By default, combine='all',
    which does both.  combine='base' will only combine::

         a   a          a                          2x      x
        x * y  =>  (x*y)   as well as things like 2   =>  4

    and combine='exp' will only combine
    ::

         a   b      (a + b)
        x * x  =>  x

    combine='exp' will strictly only combine exponents in the way that used
    to be automatic.  Also use deep=True if you need the old behavior.

    When combine='all', 'exp' is evaluated first.  Consider the first
    example below for when there could be an ambiguity relating to this.
    This is done so things like the second example can be completely
    combined.  If you want 'base' combined first, do something like
    powsimp(powsimp(expr, combine='base'), combine='exp').

    Examples
    ========

    >>> from sympy import powsimp, exp, log, symbols
    >>> from sympy.abc import x, y, z, n
    >>> powsimp(x**y*x**z*y**z, combine='all')
    x**(y + z)*y**z
    >>> powsimp(x**y*x**z*y**z, combine='exp')
    x**(y + z)*y**z
    >>> powsimp(x**y*x**z*y**z, combine='base', force=True)
    x**y*(x*y)**z

    >>> powsimp(x**z*x**y*n**z*n**y, combine='all', force=True)
    (n*x)**(y + z)
    >>> powsimp(x**z*x**y*n**z*n**y, combine='exp')
    n**(y + z)*x**(y + z)
    >>> powsimp(x**z*x**y*n**z*n**y, combine='base', force=True)
    (n*x)**y*(n*x)**z

    >>> x, y = symbols('x y', positive=True)
    >>> powsimp(log(exp(x)*exp(y)))
    log(exp(x)*exp(y))
    >>> powsimp(log(exp(x)*exp(y)), deep=True)
    x + y

    Radicals with Mul bases will be combined if combine='exp'

    >>> from sympy import sqrt, Mul
    >>> x, y = symbols('x y')

    Two radicals are automatically joined through Mul:
    >>> a=sqrt(x*sqrt(y))
    >>> a*a**3 == a**4
    True

    But if an integer power of that radical has been
    autoexpanded then Mul does not join the resulting factors:
    >>> a**4 # auto expands to a Mul, no longer a Pow
    x**2*y
    >>> _*a # so Mul doesn't combine them
    x**2*y*sqrt(x*sqrt(y))
    >>> powsimp(_) # but powsimp will
    (x*sqrt(y))**(5/2)
    >>> powsimp(x*y*a) # but won't when doing so would violate assumptions
    x*y*sqrt(x*sqrt(y))

    """
    if combine not in ['all', 'exp', 'base']:
        raise ValueError("combine must be one of ('all', 'exp', 'base').")
    y = Dummy('y')
    if expr.is_Pow:
        if deep:
            return powsimp(y*powsimp(expr.base, deep, combine, force)**powsimp(\
            expr.exp, deep, combine, force), deep, combine, force)/y
        else:
            return powsimp(y*expr, deep, combine, force)/y # Trick it into being a Mul
    elif expr.is_Function and not expr == exp_polar(1) and not expr == exp_polar(0):
        if (expr.func is exp or expr.func is exp_polar) and deep:
            # Exp should really be like Pow
            return powsimp(y*expr.func(powsimp(expr.args[0], deep, combine, force)), deep, combine, force)/y
        elif (expr.func is exp or expr.func is exp_polar) and not deep:
            return powsimp(y*expr, deep, combine, force)/y
        elif deep:
            return expr.func(*[powsimp(t, deep, combine, force) for t in expr.args])
        else:
            return expr
    elif expr.is_Add:
        return Add(*[powsimp(t, deep, combine, force) for t in expr.args])

    elif expr.is_Mul:
        if combine in ('exp', 'all'):
            # Collect base/exp data, while maintaining order in the
            # non-commutative parts of the product
            if combine == 'all' and deep and any((t.is_Add for t in expr.args)):
                # Once we get to 'base', there is no more 'exp', so we need to
                # distribute here.
                return powsimp(expand_mul(expr, deep=False), deep, combine, force)
            c_powers = defaultdict(list)
            nc_part = []
            newexpr = []
            for term in expr.args:
                if term.is_Add and deep:
                    newexpr.append(powsimp(term, deep, combine, force))
                else:
                    if term.is_commutative:
                        b, e = term.as_base_exp()
                        if deep:
                            b, e = [powsimp(i, deep, combine, force) for i in  [b, e]]
                        c_powers[b].append(e)
                    else:
                        # This is the logic that combines exponents for equal,
                        # but non-commutative bases: A**x*A**y == A**(x+y).
                        if nc_part:
                            b1, e1 = nc_part[-1].as_base_exp()
                            b2, e2 = term.as_base_exp()
                            if (b1 == b2 and
                                e1.is_commutative and e2.is_commutative):
                                nc_part[-1] = Pow(b1, Add(e1, e2))
                                continue
                        nc_part.append(term)

            # add up exponents of common bases
            for b, e in c_powers.iteritems():
                c_powers[b] = Add(*e)

            # check for base and inverted base pairs
            be = c_powers.items()
            skip = set() # skip if we already saw them
            for b, e in be:
                if b in skip:
                    continue
                bpos = b.is_positive or b.is_polar
                if bpos:
                    binv = 1/b
                    if b != binv and binv in c_powers:
                        if b.as_numer_denom()[0] is S.One:
                            c_powers.pop(b)
                            c_powers[binv] -= e
                        else:
                            skip.add(binv)
                            e = c_powers.pop(binv)
                            c_powers[b] -= e

            # filter c_powers and convert to a list
            c_powers = [(b, e) for b, e in c_powers.iteritems() if e]

            # ==============================================================
            # check for Mul bases of Rational powers that can be combined with
            # separated bases, e.g. x*sqrt(x*y)*sqrt(x*sqrt(x*y)) -> (x*sqrt(x*y))**(3/2)
            # ---------------- helper functions
            def ratq(x):
                '''Return Rational part of x's exponent as it appears in the bkey.
                '''
                return bkey(x)[0][1]

            def bkey(b, e=None):
                '''Return (b**s, c.q), c.p where e -> c*s. If e is not given then
                it will be taken by using as_base_exp() on the input b.
                e.g.
                    x**3/2 -> (x, 2), 3
                    x**y -> (x**y, 1), 1
                    x**(2*y/3) -> (x**y, 3), 2

                >>> x+2

                '''
                if e is not None: # coming from c_powers or from below
                    if e.is_Integer:
                        return (b, S.One), e
                    elif e.is_Rational:
                        return (b, Integer(e.q)), Integer(e.p)
                    else:
                        c, m = e.as_coeff_mul()
                        if c is not S.One:
                            return (b**Mul._from_args(m), Integer(c.q)), Integer(c.p)
                        else:
                            return (b**e, S.One), S.One
                else:
                    return bkey(*b.as_base_exp())

            def update(b):
                '''Decide what to do with base, b. If its exponent is now an
                integer multiple of the Rational denominator, then remove it
                and put the factors of its base in the common_b dictionary or
                update the existing bases if necessary. If it has been zeroed
                out, simply remove the base.
                '''
                newe, r = divmod(common_b[b], b[1])
                if not r:
                    common_b.pop(b)
                    if newe:
                        for m in Mul.make_args(b[0]**newe):
                            b, e = bkey(m)
                            if b not in common_b:
                                common_b[b] = 0
                            common_b[b] += e
                            if b[1] != 1:
                                bases.append(b)
            # ---------------- end of helper functions

            # assemble a dictionary of the factors having a Rational power
            common_b = {}
            done = []
            bases = []
            for b, e in c_powers:
                b, e = bkey(b, e)
                common_b[b] = e
                if b[1] != 1 and b[0].is_Mul:
                    bases.append(b)
            bases.sort(key=default_sort_key) # this makes tie-breaking canonical
            bases.sort(key=measure, reverse= True) # handle longest first
            for base in bases:
                if base not in common_b: # it may have been removed already
                    continue
                b, exponent = base
                last = False # True when no factor of base is a radical
                qlcm = 1 # the lcm of the radical denominators
                while True:
                    bstart = b
                    qstart = qlcm

                    bb = [] # list of factors
                    ee = [] # (factor's exponent, current value of that exponent in common_b)
                    for bi in Mul.make_args(b):
                        bib, bie = bkey(bi)
                        if bib not in common_b or common_b[bib] < bie:
                            ee = bb = [] # failed
                            break
                        ee.append([bie, common_b[bib]])
                        bb.append(bib)
                    if ee:
                        # find the number of extractions possible
                        # e.g. [(1, 2), (2, 2)] -> min(2/1, 2/2) -> 1
                        min1 = ee[0][1]/ee[0][0]
                        for i in xrange(len(ee)):
                            rat = ee[i][1]/ee[i][0]
                            if rat < 1:
                                break
                            min1 = min(min1, rat)
                        else:
                            # update base factor counts
                            # e.g. if ee = [(2, 5), (3, 6)] then min1 = 2
                            # and the new base counts will be 5-2*2 and 6-2*3
                            for i in xrange(len(bb)):
                                common_b[bb[i]] -= min1*ee[i][0]
                                update(bb[i])
                            # update the count of the base
                            # e.g. x**2*y*sqrt(x*sqrt(y)) the count of x*sqrt(y)
                            # will increase by 4 to give bkey (x*sqrt(y), 2, 5)
                            common_b[base] += min1*qstart*exponent
                    if (last # no more radicals in base
                        or len(common_b) == 1 # nothing left to join with
                        or all(k[1] == 1 for k in common_b) # no radicals left in common_b
                        ):
                        break
                    # see what we can exponentiate base by to remove any radicals
                    # so we know what to search for
                    # e.g. if base were x**(1/2)*y**(1/3) then we should exponentiate
                    # by 6 and look for powers of x and y in the ratio of 2 to 3
                    qlcm = lcm([ratq(bi) for bi in Mul.make_args(bstart)])
                    if qlcm == 1:
                        break # we are done
                    b = bstart**qlcm
                    qlcm *= qstart
                    if all(ratq(bi) == 1 for bi in Mul.make_args(b)):
                        last = True # we are going to be done after this next pass
                # this base no longer can find anything to join with and
                # since it was longer than any other we are done with it
                b, q = base
                done.append((b, common_b.pop(base)*Rational(1, q)))

            # update c_powers and get ready to continue with powsimp
            c_powers = done
            # there may be terms still in common_b that were bases that were
            # identified as needing processing, so remove those, too
            for (b, q), e in common_b.items():
                if b.is_Pow and q is not S.One and not b.exp.is_Rational:
                    b, be = b.as_base_exp()
                    b = b**(be/q)
                else:
                    b = root(b, q)
                c_powers.append((b, e))
            check = len(c_powers)
            c_powers = dict(c_powers)
            assert len(c_powers) == check # there should have been no duplicates
            # ==============================================================

            # rebuild the expression
            newexpr = Mul(*(newexpr + [Pow(b, e) for b, e in c_powers.iteritems()]))
            if combine == 'exp':
                return Mul(newexpr, Mul(*nc_part))
            else:
                # combine is 'all', get stuff ready for 'base'
                if deep:
                    newexpr = expand_mul(newexpr, deep=False)
                if newexpr.is_Add:
                    return powsimp(Mul(*nc_part), deep, combine='base', force=force) * \
                           Add(*[powsimp(i, deep, combine='base', force=force)
                                 for i in newexpr.args])
                else:
                    return powsimp(Mul(*nc_part), deep, combine='base', force=force)*\
                    powsimp(newexpr, deep, combine='base', force=force)

        else:
            # combine is 'base'
            if deep:
                expr = expand_mul(expr, deep=False)
            if expr.is_Add:
                return Add(*[powsimp(i, deep, combine, force) for i in expr.args])
            else:
                # Build c_powers and nc_part.  These must both be lists not
                # dicts because exp's are not combined.
                c_powers = []
                nc_part = []
                for term in expr.args:
                    if term.is_commutative:
                        c_powers.append(list(term.as_base_exp()))
                    else:
                        # This is the logic that combines bases that are
                        # different and non-commutative, but with equal and
                        # commutative exponents: A**x*B**x == (A*B)**x.
                        if nc_part:
                            b1, e1 = nc_part[-1].as_base_exp()
                            b2, e2 = term.as_base_exp()
                            if (e1 == e2 and e2.is_commutative):
                                nc_part[-1] = Pow(Mul(b1, b2), e1)
                                continue
                        nc_part.append(term)

            # Pull out numerical coefficients from exponent if assumptions allow
            # e.g., 2**(2*x) => 4**x
            for i in xrange(len(c_powers)):
                b, e = c_powers[i]
                if not (b.is_nonnegative or e.is_integer or force or b.is_polar):
                    continue
                exp_c, exp_t = e.as_coeff_mul()
                if exp_c is not S.One and exp_t:
                    c_powers[i] = [Pow(b, exp_c), e._new_rawargs(*exp_t)]


            # Combine bases whenever they have the same exponent and
            # assumptions allow

            # first gather the potential bases under the common exponent
            c_exp = defaultdict(list)
            for b, e in c_powers:
                if deep:
                    e = powsimp(e, deep, combine, force)
                c_exp[e].append(b)
            del c_powers

            # Merge back in the results of the above to form a new product
            c_powers = defaultdict(list)
            for e in c_exp:
                bases = c_exp[e]

                # calculate the new base for e
                if len(bases) == 1:
                    new_base = bases[0]
                elif e.is_integer or force:
                    new_base = Mul(*bases)
                else:
                    # see which ones can be joined
                    unk=[]
                    nonneg=[]
                    neg=[]
                    for bi in bases:
                        if bi.is_negative is not None: #then we know the sign
                            if bi.is_negative:
                                neg.append(bi)
                            else:
                                nonneg.append(bi)
                        elif bi.is_polar:
                            nonneg.append(bi) # polar can be treated like non-negative
                        else:
                            unk.append(bi)
                    if len(unk) == 1 and not neg or len(neg) == 1 and not unk:
                        # a single neg or a single unk can join the rest
                        nonneg.extend(unk + neg)
                        unk = neg = []
                    elif neg:
                        # their negative signs cancel in pairs
                        neg = [-w for w in neg]
                        if len(neg) % 2:
                            unk.append(S.NegativeOne)

                    # these shouldn't be joined
                    for b in unk:
                        c_powers[b].append(e)
                    # here is a new joined base
                    new_base = Mul(*(nonneg + neg))

                c_powers[new_base].append(e)

            # break out the powers from c_powers now
            c_part = []
            if combine == 'all':
                #...joining the exponents
                for b, e in c_powers.iteritems():
                    c_part.append(Pow(b, Add(*e)))
            else:
                #...joining nothing
                for b, e in c_powers.iteritems():
                    for ei in e:
                        c_part.append(Pow(b, ei))

            # we're done
            return Mul(*(c_part + nc_part))

    else:
        return expr

def hypersimp(f, k):
    """Given combinatorial term f(k) simplify its consecutive term ratio
       i.e. f(k+1)/f(k).  The input term can be composed of functions and
       integer sequences which have equivalent representation in terms
       of gamma special function.

       The algorithm performs three basic steps:

       1. Rewrite all functions in terms of gamma, if possible.

       2. Rewrite all occurrences of gamma in terms of products
          of gamma and rising factorial with integer,  absolute
          constant exponent.

       3. Perform simplification of nested fractions, powers
          and if the resulting expression is a quotient of
          polynomials, reduce their total degree.

       If f(k) is hypergeometric then as result we arrive with a
       quotient of polynomials of minimal degree. Otherwise None
       is returned.

       For more information on the implemented algorithm refer to:

       1. W. Koepf, Algorithms for m-fold Hypergeometric Summation,
          Journal of Symbolic Computation (1995) 20, 399-417
    """
    f = sympify(f)

    g = f.subs(k, k+1) / f

    g = g.rewrite(gamma)
    g = expand_func(g)
    g = powsimp(g, deep=True, combine='exp')

    if g.is_rational_function(k):
        return simplify(g, ratio=S.Infinity)
    else:
        return None

def hypersimilar(f, g, k):
    """Returns True if 'f' and 'g' are hyper-similar.

       Similarity in hypergeometric sense means that a quotient of
       f(k) and g(k) is a rational function in k.  This procedure
       is useful in solving recurrence relations.

       For more information see hypersimp().

    """
    f, g = map(sympify, (f, g))

    h = (f/g).rewrite(gamma)
    h = h.expand(func=True, basic=False)

    return h.is_rational_function(k)

def combsimp(expr):
    r"""
    Simplify combinatorial expressions.

    This function takes as input an expression containing factorials,
    binomials, Pochhammer symbol and other "combinatorial" functions,
    and tries to minimize the number of those functions and reduce
    the size of their arguments. The result is be given in terms of
    binomials and factorials.

    The algorithm works by rewriting all combinatorial functions as
    expressions involving rising factorials (Pochhammer symbols) and
    applies recurrence relations and other transformations applicable
    to rising factorials, to reduce their arguments, possibly letting
    the resulting rising factorial to cancel. Rising factorials with
    the second argument being an integer are expanded into polynomial
    forms and finally all other rising factorial are rewritten in terms
    more familiar functions. If the initial expression contained any
    combinatorial functions, the result is expressed using binomial
    coefficients and gamma functions. If the initial expression consisted
    of gamma functions alone, the result is expressed in terms of gamma
    functions.

    If the result is expressed using gamma functions, the following three
    additional steps are performed:

    1. Reduce the number of gammas by applying the reflection theorem
       gamma(x)*gamma(1-x) == pi/sin(pi*x).
    2. Reduce the number of gammas by applying the multiplication theorem
       gamma(x)*gamma(x+1/n)*...*gamma(x+(n-1)/n) == C*gamma(n*x).
    3. Reduce the number of prefactors by absorbing them into gammas, where
       possible.

    All transformation rules can be found (or was derived from) here:

    1. http://functions.wolfram.com/GammaBetaErf/Pochhammer/17/01/02/
    2. http://functions.wolfram.com/GammaBetaErf/Pochhammer/27/01/0005/

    Examples
    ========

    >>> from sympy.simplify import combsimp
    >>> from sympy import factorial, binomial
    >>> from sympy.abc import n, k

    >>> combsimp(factorial(n)/factorial(n - 3))
    n*(n - 2)*(n - 1)
    >>> combsimp(binomial(n+1, k+1)/binomial(n, k))
    (n + 1)/(k + 1)

    """
    factorial = C.factorial
    binomial = C.binomial
    gamma = C.gamma

    # as a rule of thumb, if the expression contained gammas initially, it
    # probably makes sense to retain them
    as_gamma = not expr.has(factorial, binomial)

    def as_coeff_Add(expr):
        if expr.is_Add:
            coeff, args = expr.args[0], expr.args[1:]

            if coeff.is_Number:
                if len(args) == 1:
                    return coeff, args[0]
                else:
                    return coeff, expr._new_rawargs(*args)

        return S.Zero, expr

    class rf(Function):
        @classmethod
        def eval(cls, a, b):
            if b.is_Integer:
                if not b:
                    return S.Zero

                n, result = int(b), S.One

                if n > 0:
                    for i in xrange(0, n):
                        result *= a + i

                    return result
                else:
                    for i in xrange(1, -n+1):
                        result *= a - i

                    return 1/result
            else:
                if b.is_Add:
                    c, _b = b.as_coeff_Add()

                    if c.is_Integer:
                        if c > 0:
                            return rf(a, _b)*rf(a+_b, c)
                        elif c < 0:
                            return rf(a, _b)/rf(a+_b+c, -c)

                if a.is_Add:
                    c, _a = a.as_coeff_Add()

                    if c.is_Integer:
                        if c > 0:
                            return rf(_a, b)*rf(_a+b, c)/rf(_a, c)
                        elif c < 0:
                            return rf(_a, b)*rf(_a+c, -c)/rf(_a+b+c, -c)

    expr = expr.replace(binomial,
        lambda n, k: rf((n-k+1).expand(), k.expand())/rf(1, k.expand()))
    expr = expr.replace(factorial,
        lambda n: rf(1, n.expand()))
    expr = expr.replace(gamma,
        lambda n: rf(1, (n-1).expand()))

    if as_gamma:
        expr = expr.replace(rf,
            lambda a, b: gamma(a + b)/gamma(a))
    else:
        expr = expr.replace(rf,
            lambda a, b: binomial(a+b-1, b)*factorial(b))

    def rule(n, k):
        coeff, rewrite = S.One, False

        cn, _n = n.as_coeff_Add()
        ck, _k = k.as_coeff_Add()

        if _n and cn.is_Integer and cn:
            coeff *= rf(_n + 1, cn)/rf(_n - k + 1, cn)
            rewrite = True
            n = _n

        if _k and ck.is_Integer and ck:
            coeff *= rf(n - ck - _k + 1, ck)/rf(_k + 1, ck)
            rewrite = True
            k = _k

        if rewrite:
            return coeff*binomial(n, k)

    expr = expr.replace(binomial, rule)

    def rule_gamma(expr):
        """ Simplify products of gamma functions further. """
        from itertools import count
        from sympy.core.compatibility import permutations
        if expr.is_Atom:
            return expr
        args = [rule_gamma(x) for x in expr.args]
        if not expr.is_Mul:
            return expr.func(*args)
        numer_gammas = []
        denom_gammas = []
        numer_others = []
        denom_others = []
        newargs = list(args[:])
        while newargs:
            arg = newargs.pop()
            if arg.is_Pow and arg.exp.is_Integer:
                if arg.exp == -1:
                    if isinstance(arg.base, gamma):
                        denom_gammas.append(arg.base.args[0])
                    else:
                        denom_others.append(arg.base)
                    continue
                n = abs(arg.exp)
                if arg.exp < 0:
                    arg = 1/arg.base
                else:
                    arg = arg.base
                for _ in range(n):
                    newargs.append(arg)
            elif isinstance(arg, gamma):
                numer_gammas.append(arg.args[0])
            else:
                numer_others.append(arg)

        # Try to reduce the number of gamma factors by applying the
        # reflection formula gamma(x)*gamma(1-x) = pi/sin(pi*x)
        for l, numer, denom in [(numer_gammas, numer_others, denom_others),
                                (denom_gammas, denom_others, numer_others)]:
            newl = []
            while l:
                t = l.pop()
                append = True
                for i in range(len(l)):
                    g = l[i]
                    n = simplify(t + g - 1)
                    if not n.is_Integer or t.is_integer:
                        continue
                    append = False
                    numer.append(S.Pi)
                    denom.append(C.sin(S.Pi*t))
                    l.pop(i)
                    if n > 0:
                        for k in range(n):
                            numer.append(1 - t + k)
                    else:
                        for k in range(-n):
                            denom.append(-t - k)
                    break
                if append:
                    newl.append(t)
            l += newl

        # Try to reduce the number of gamma factors by applying the
        # multiplication theorem.
        for l, numer, denom in [(numer_gammas, numer_others, denom_others),
                                (denom_gammas, denom_others, numer_others)]:
            changed = True
            while changed:
                newl = []
                changed = False
                differences = {}
                differences2 = {}
                # differences maps pairs (g1, g2) of indices to their rational
                # difference mod 1: l[g2] - l[g1] % 1
                # (if difference is not rational, no entry)
                # differences2 maps g1 to dicts rational -> g2, so that
                # differences2[g1][r] is a list of g2 with g2-g1 % 1 = r
                # (we store indices instead of arguments in order to have unique
                #  tokens)
                for g1, g2 in permutations(range(len(l)), 2):
                    r = simplify(l[g2] - l[g1])
                    if r.is_Rational:
                        differences[(g1, g2)] = r % 1
                        differences2.setdefault(g1, {}).setdefault(r % 1, []).append(g2)
                diffs = differences.items()
                diffs.sort(key=lambda x:x[1])
                erased = set()
                # erased keeps track of keys we erased ...
                for (idx1, idx2), d in diffs:
                    if d.p != 1 or d <= 0 or idx1 in erased:
                        continue
                    others = []
                    for u in range(1, d.q):
                        x = S(u)/d.q
                        if not x in differences2[idx1]:
                            break
                        for idx2 in differences2[idx1][x]:
                            if not idx2 in erased:
                                others.append(idx2)
                                break
                    if len(others) != d.q - 1:
                        continue
                    erased.add(idx1)
                    for o in others: erased.add(o)
                    changed = True
                    # If we arrive here, we found something to apply the theorem
                    # to: idx1, *others.
                    # We need to
                    # 1) convert all the gamma functions to have the right
                    #    argument (could be off by an integer)
                    # 2) append the factors corresponding to the theorem
                    # 3) append the new gamma function
                    # (1)
                    for u in others:
                        n = simplify(l[u] - l[idx1] - differences[(idx1, u)])
                        if n > 0:
                            for k in range(n):
                                numer.append(l[u] - k - 1)
                        if n < 0:
                            for k in range(-n):
                                denom.append(l[u] - k)
                    # (2)
                    numer.append((2*S.Pi)**(S(d.q - 1)/2)*d.q**(S(1)/2-d.q*l[idx1]))
                    # (3)
                    newl.append(l[idx1]*d.q)
                for idx in range(len(l)):
                    if not idx in erased:
                        newl.append(l[idx])
                while l: l.pop()
                l += newl # Note l is empty before this

        # Try to reduce the number of gammas by using the duplication
        # theorem to cancel an upper and lower.
        # e.g. gamma(2*s)/gamma(s) = gamma(s)*gamma(s+1/2)*C/gamma(s)
        # (in principle this can also be done with with factors other than two,
        #  but two is special in that we need only matching numer and denom, not
        #  several in numer).
        for ng, dg, no, do in [(numer_gammas, denom_gammas, numer_others,
                                denom_others),
                               (denom_gammas, numer_gammas, denom_others,
                                numer_others)]:
            changed = True
            while changed:
                changed = False
                found = None
                for x in ng:
                    for y in dg:
                        if simplify(2*y-x).is_Integer:
                            found = (x, y)
                            break
                    if found:
                        break
                if not found:
                    break
                changed = True
                x, y = found
                n = simplify(x - 2*y)
                ng.remove(x)
                dg.remove(y)
                if n > 0:
                    for k in xrange(n):
                        no.append(2*y + k)
                elif n < 0:
                    for k in xrange(-n):
                        do.append(2*y - 1 - k)
                ng.append(y + S(1)/2)
                no.append(2**(2*y - 1))
                do.append(sqrt(S.Pi))

        # Try to absorb factors into the gammas
        for to, numer, denom in [(numer_gammas, numer_others, denom_others),
                                 (denom_gammas, denom_others, numer_others)]:
            newl = []
            while to:
                g = to.pop()
                cont = True
                while cont:
                    cont = False
                    def find_fuzzy(l, x):
                        for y in l:
                            # XXX we want some simplification (e.g. cancel or
                            # simplify) but no matter what it's slow.
                            a = len(cancel(x/y).free_symbols)
                            b = len(x.free_symbols)
                            c = len(y.free_symbols)
                            # TODO is there a better heuristic?
                            if a == 0 and (b > 0 or c > 0):
                                return y
                    y = find_fuzzy(numer, g)
                    if y is not None:
                        numer.remove(y)
                        if y != g:
                            numer.append(y/g)
                        g += 1
                        cont = True
                    y = find_fuzzy(numer, 1/(g-1))
                    if y is not None:
                        numer.remove(y)
                        if y != 1/(g-1):
                            numer.append((g-1)*y)
                        g -= 1
                        cont = True
                    y = find_fuzzy(denom, 1/g)
                    if y is not None:
                        denom.remove(y)
                        if y != 1/g:
                            denom.append(y*g)
                        g += 1
                        cont = True
                    y = find_fuzzy(denom, g - 1)
                    if y is not None:
                        denom.remove(y)
                        if y != g - 1:
                            numer.append((g-1)/y)
                        g -= 1
                        cont = True
                newl.append(g)
            to += newl

        return C.Mul(*[gamma(g) for g in numer_gammas]) \
             / C.Mul(*[gamma(g) for g in denom_gammas]) \
             * C.Mul(*numer_others) / C.Mul(*denom_others)

    # (for some reason we cannot use Basic.replace in this case)
    expr = rule_gamma(expr)

    return factor(expr)

def simplify(expr, ratio=1.7, measure=count_ops):
    """
    Simplifies the given expression.

    Simplification is not a well defined term and the exact strategies
    this function tries can change in the future versions of SymPy. If
    your algorithm relies on "simplification" (whatever it is), try to
    determine what you need exactly  -  is it powsimp()?, radsimp()?,
    together()?, logcombine()?, or something else? And use this particular
    function directly, because those are well defined and thus your algorithm
    will be robust.

    Nonetheless, especially for interactive use, or when you don't know
    anything about the structure of the expression, simplify() tries to apply
    intelligent heuristics to make the input expression "simpler".  For
    example:

    >>> from sympy import simplify, cos, sin
    >>> from sympy.abc import x, y
    >>> a = (x + x**2)/(x*sin(y)**2 + x*cos(y)**2)
    >>> a
    (x**2 + x)/(x*sin(y)**2 + x*cos(y)**2)
    >>> simplify(a)
    x + 1

    Note that we could have obtained the same result by using specific
    simplification functions:

    >>> from sympy import trigsimp, cancel
    >>> b = trigsimp(a)
    >>> b
    (x**2 + x)/x
    >>> c = cancel(b)
    >>> c
    x + 1

    In some cases, applying :func:`simplify` may actually result in some more
    complicated expression. The default ``ratio=1.7`` prevents more extreme
    cases: if (result length)/(input length) > ratio, then input is returned
    unmodified.  The ``measure`` parameter lets you specify the function used
    to determine how complex an expression is.  The function should take a
    single argument as an expression and return a number such that if
    expression ``a`` is more complex than expression ``b``, then
    ``measure(a) > measure(b)``.  The default measure function is
    :func:`count_ops`, which returns the total number of operations in the
    expression.

    For example, if ``ratio=1``, ``simplify`` output can't be longer
    than input.

    ::

        >>> from sympy import sqrt, simplify, count_ops, oo
        >>> root = 1/(sqrt(2)+3)

    Since ``simplify(root)`` would result in a slightly longer expression,
    root is returned unchanged instead::

       >>> simplify(root, ratio=1) == root
       True

    If ``ratio=oo``, simplify will be applied anyway::

        >>> count_ops(simplify(root, ratio=oo)) > count_ops(root)
        True

    Another issue to be aware of if using ``ratio=oo`` is that simplification
    of a denominator containing a sqrt may lead to an expression which is not
    strictly valid. If ``ratio`` is not changed, this transformation doesn't
    (usually) happen since it would lead to a longer expression:

        >>> from sympy.abc import a, b, c
        >>> from sympy import sqrt
        >>> eq = 1/(a + b*sqrt(c))
        >>> simplify(eq) == eq
        True
        >>> forced = simplify(eq, ratio=oo)
        >>> forced == eq
        False
        >>> eq.subs(a, b*sqrt(c))
        1/(2*b*sqrt(c))
        >>> forced.subs(a, b*sqrt(c))
        nan
        >>> forced
        (a - b*sqrt(c))/(a**2 - b**2*c)

    Note that the shortest expression is not necessary the simplest, so
    setting ``ratio`` to 1 may not be a good idea.
    Heuristically, the default value ``ratio=1.7`` seems like a reasonable
    choice.

    You can easily define your own measure function based on what you feel
    should represent the "size" or "complexity" of the input expression.  Note
    that some choices, such as ``lambda expr: len(str(expr))`` may appear to be
    good metrics, but have other problems (in this case, the measure function
    may slow down simplify too much for very large expressions).  If you don't
    know what a good metric would be, the default, ``count_ops``, is a good one.

    For example:

    >>> from sympy import symbols, log
    >>> a, b = symbols('a b', positive=True)
    >>> g = log(a) + log(b) + log(a)*log(1/b)
    >>> h = simplify(g)
    >>> h
    log(a*b**(log(1/a) + 1))
    >>> count_ops(g)
    8
    >>> count_ops(h)
    6

    So you can see that ``h`` is simpler than ``g`` using the count_ops metric.
    However, we may not like how ``simplify`` (in this case, using
    ``logcombine``) has created the ``b**(log(1/a) + 1)`` term.  A simple way to
    reduce this would be to give more weight to powers as operations in
    ``count_ops``.  We can do this by using the ``visual=True`` option:

    >>> print count_ops(g, visual=True)
    2*ADD + DIV + 4*LOG + MUL
    >>> print count_ops(h, visual=True)
    ADD + DIV + 2*LOG + MUL + POW

    >>> from sympy import Symbol, S
    >>> def my_measure(expr):
    ...     POW = Symbol('POW')
    ...     # Discourage powers by giving POW a weight of 10
    ...     count = count_ops(expr, visual=True).subs(POW, 10)
    ...     # Every other operation gets a weight of 1 (the default)
    ...     count = count.replace(Symbol, type(S.One))
    ...     return count
    >>> my_measure(g)
    8
    >>> my_measure(h)
    15
    >>> 15./8 > 1.7 # 1.7 is the default ratio
    True
    >>> simplify(g, measure=my_measure)
    -log(a)*log(b) + log(a) + log(b)

    Note that because ``simplify()`` internally tries many different
    simplification strategies and then compares them using the measure
    function, we get a completely different result that is still different
    from the input expression by doing this.
    """
    expr = sympify(expr)

    if not isinstance(expr, Basic): # XXX: temporary hack
        return expr

    if isinstance(expr, Atom):
        return expr

    if isinstance(expr, C.Relational):
        return expr.__class__(simplify(expr.lhs, ratio=ratio),
                              simplify(expr.rhs, ratio=ratio))

    # TODO: Apply different strategies, considering expression pattern:
    # is it a purely rational function? Is there any trigonometric function?...
    # See also https://github.com/sympy/sympy/pull/185.

    original_expr = expr

    def shorter(*choices):
        '''Return the choice that has the fewest ops. In case of a tie,
        the expression listed first is selected.'''
        if len(set(choices)) == 1:
            return choices[0]
        return min(choices, key=measure)

    if expr.is_commutative is False:
        expr1 = factor_terms(together(powsimp(expr)))
        if ratio is S.Infinity:
            return expr1
        return shorter(expr1, expr)

    expr1 = cancel(powsimp(expr))
    expr2 = together(expr1.expand(), deep=True)
    if ratio is S.Infinity:
        expr = expr2
    else:
        expr = shorter(expr2, expr1, expr)

    if not isinstance(expr, Basic): # XXX: temporary hack
        return expr

    if expr.has(C.TrigonometricFunction):
        expr = trigsimp(expr)

    if expr.has(C.log):
        expr = shorter(expand_log(expr, deep=True), logcombine(expr))

    if expr.has(C.CombinatorialFunction, gamma):
        expr = combsimp(expr)

    expr = powsimp(expr, combine='exp', deep=True)
    numer, denom = expr.as_numer_denom()
    if denom.is_Add:
        a, b, c = map(Wild, 'abc')

        # cancel already took care of things like 1/sqrt(3) -> sqrt(3)/3
        # so we don't have to worry about `a` matching with `b`=0 as we
        # do in radsimp yet, but we do below...
        r = denom.match(a + b*sqrt(c))

        if r is not None and r[b]:
            # be careful not to multiply by 0/0 when removing denom;
            # this will happen in a = +/- b*sqrt(c), so collect c so
            # it's not also in `a` but this may turn the denom into
            # a Mul so we have to watch out for that.
            if r[c].is_number:
                newdenom = collect_const(denom, sqrt(r[c]))
                if newdenom != denom:
                    if newdenom.is_Add:
                        r = newdenom.match(a + b*sqrt(c))
                    else:
                        r = None # Add turned into a Mul
            if r:
                a, b, c = r[a], r[b], r[c]

                numer *= a-b*sqrt(c)
                numer = numer.expand()

                denom = a**2 - c*b**2

                expr = numer/denom

    if expr.could_extract_minus_sign():
        n, d = expr.as_numer_denom()
        if d != 0:
            expr = -n/(-d)

    if measure(expr) > ratio*measure(original_expr):
        return original_expr

    if original_expr.is_Matrix:
        expr = matrixify(expr)

    return expr

def _real_to_rational(expr):
    """
    Replace all reals in expr with rationals.

    >>> from sympy import nsimplify
    >>> from sympy.abc import x

    >>> nsimplify(.76 + .1*x**.5, rational=True)
    sqrt(x)/10 + 19/25

    """
    p = expr
    for r in p.atoms(C.Float):
        newr = nsimplify(r, rational=False)
        if not newr.is_Rational or \
           r.is_finite and not newr.is_finite:
            newr = r
            if newr < 0:
                s = -1
                newr *= s
            else:
                s = 1
            d = Pow(10, int((mpmath.log(newr)/mpmath.log(10))))
            newr = s*Rational(str(newr/d))*d
        p = p.subs(r, newr)
    return p

def nsimplify(expr, constants=[], tolerance=None, full=False, rational=None):
    """
    Find a simple representation for a number or, if there are free symbols or
    if rational=True, then replace Floats with their Rational equivalents. If
    no change is made and rational is not False then Floats will at least be
    converted to Rationals.

    For numerical expressions, a simple formula that numerically matches the
    given numerical expression is sought (and the input should be possible
    to evalf to a precision of at least 30 digits).

    Optionally, a list of (rationally independent) constants to
    include in the formula may be given.

    A lower tolerance may be set to find less exact matches. If no tolerance
    is given then the least precise value will set the tolerance (e.g. Floats
    default to 15 digits of precision, so would be tolerance=10**-15).

    With full=True, a more extensive search is performed
    (this is useful to find simpler numbers when the tolerance
    is set low).

    Examples
    ========

        >>> from sympy import nsimplify, sqrt, GoldenRatio, exp, I, exp, pi
        >>> nsimplify(4/(1+sqrt(5)), [GoldenRatio])
        -2 + 2*GoldenRatio
        >>> nsimplify((1/(exp(3*pi*I/5)+1)))
        1/2 - I*sqrt(sqrt(5)/10 + 1/4)
        >>> nsimplify(I**I, [pi])
        exp(-pi/2)
        >>> nsimplify(pi, tolerance=0.01)
        22/7

    """
    expr = sympify(expr)
    if rational or expr.free_symbols:
        return _real_to_rational(expr)

    # sympy's default tolarance for Rationals is 15; other numbers may have
    # lower tolerances set, so use them to pick the largest tolerance if none
    # was given
    tolerance = tolerance or 10**-min([15] +
                                     [mpmath.libmp.libmpf.prec_to_dps(n._prec)
                                     for n in expr.atoms(Float)])

    prec = 30
    bprec = int(prec*3.33)

    constants_dict = {}
    for constant in constants:
        constant = sympify(constant)
        v = constant.evalf(prec)
        if not v.is_Float:
            raise ValueError("constants must be real-valued")
        constants_dict[str(constant)] = v._to_mpmath(bprec)

    exprval = expr.evalf(prec, chop=True)
    re, im = exprval.as_real_imag()

    # Must be numerical
    if not ((re.is_Float or re.is_Integer) and (im.is_Float or im.is_Integer)):
        return expr

    def nsimplify_real(x):
        orig = mpmath.mp.dps
        xv = x._to_mpmath(bprec)
        try:
            # We'll be happy with low precision if a simple fraction
            if not (tolerance or full):
                mpmath.mp.dps = 15
                rat = mpmath.findpoly(xv, 1)
                if rat is not None:
                    return Rational(-int(rat[1]), int(rat[0]))
            mpmath.mp.dps = prec
            newexpr = mpmath.identify(xv, constants=constants_dict,
                tol=tolerance, full=full)
            if not newexpr:
                raise ValueError
            if full:
                newexpr = newexpr[0]
            expr = sympify(newexpr)
            if expr.is_finite is False and not xv in [mpmath.inf, mpmath.ninf]:
                raise ValueError
            return expr
        finally:
            # even though there are returns above, this is executed
            # before leaving
            mpmath.mp.dps = orig
    try:
        if re: re = nsimplify_real(re)
        if im: im = nsimplify_real(im)
    except ValueError:
        if rational is None:
            return _real_to_rational(expr)
        return expr

    rv = re + im*S.ImaginaryUnit
    # if there was a change or rational is explicitly not wanted
    # return the value, else return the Rational representation
    if rv != expr or rational is False:
        return rv
    return _real_to_rational(expr)



def logcombine(expr, force=False):
    """
    Takes logarithms and combines them using the following rules:

    - log(x)+log(y) == log(x*y)
    - a*log(x) == log(x**a)

    These identities are only valid if x and y are positive and if a is real,
    so the function will not combine the terms unless the arguments have the
    proper assumptions on them.  Use logcombine(func, force=True) to
    automatically assume that the arguments of logs are positive and that
    coefficients are real.  Note that this will not change any assumptions
    already in place, so if the coefficient is imaginary or the argument
    negative, combine will still not combine the equations.  Change the
    assumptions on the variables to make them combine.

    Examples
    ========

    >>> from sympy import Symbol, symbols, log, logcombine
    >>> from sympy.abc import a, x, y, z
    >>> logcombine(a*log(x)+log(y)-log(z))
    a*log(x) + log(y) - log(z)
    >>> logcombine(a*log(x)+log(y)-log(z), force=True)
    log(x**a*y/z)
    >>> x,y,z = symbols('x,y,z', positive=True)
    >>> a = Symbol('a', real=True)
    >>> logcombine(a*log(x)+log(y)-log(z))
    log(x**a*y/z)

    """
    # Try to make (a+bi)*log(x) == a*log(x)+bi*log(x).  This needs to be a
    # separate function call to avoid infinite recursion.
    expr = expand_mul(expr, deep=False)
    return _logcombine(expr, force)

def _logcombine(expr, force=False):
    """
    Does the main work for logcombine, it's a separate function to avoid an
    infinite recursion. See the docstrings of logcombine() for help.
    """
    def _getlogargs(expr):
        """
        Returns the arguments of the logarithm in an expression.

        Examples
        ========

        _getlogargs(a*log(x*y))
        x*y
        """
        if expr.func is log:
            return [expr.args[0]]
        else:
            args = []
            for i in expr.args:
                if i.func is log:
                    args.append(_getlogargs(i))
            return flatten(args)
        return None

    if type(expr) in (int, float) or expr.is_Number or expr.is_Rational or \
        expr.is_NumberSymbol or type(expr) == C.Integral:
        return expr

    if isinstance(expr, Equality):
        retval = Equality(_logcombine(expr.lhs-expr.rhs, force),\
        Integer(0))
        # If logcombine couldn't do much with the equality, try to make it like
        # it was.  Hopefully extract_additively won't become smart enought to
        # take logs apart :)
        right = retval.lhs.extract_additively(expr.lhs)
        if right:
            return Equality(expr.lhs, _logcombine(-right, force))
        else:
            return retval

    if expr.is_Add:
        argslist = 1
        notlogs = 0
        coeflogs = 0
        for i in expr.args:
            if i.func is log:
                if (i.args[0].is_positive or (force and not \
                i.args[0].is_nonpositive)):
                    argslist *= _logcombine(i.args[0], force)
                else:
                    notlogs += i
            elif i.is_Mul and any(map(lambda t: getattr(t,'func', False)==log,\
            i.args)):
                largs = _getlogargs(i)
                assert len(largs) != 0
                loglargs = 1
                for j in largs:
                    loglargs *= log(j)

                if all(getattr(t,'is_positive') for t in largs)\
                    and getattr(i.extract_multiplicatively(loglargs),'is_real', False)\
                    or (force\
                        and not all(getattr(t,'is_nonpositive') for t in largs)\
                        and not getattr(i.extract_multiplicatively(loglargs),\
                        'is_real')==False):

                    coeflogs += _logcombine(i, force)
                else:
                    notlogs += i
            elif i.has(log):
                notlogs += _logcombine(i, force)
            else:
                notlogs += i
        if notlogs + log(argslist) + coeflogs == expr:
            return expr
        else:
            alllogs = _logcombine(log(argslist) + coeflogs, force)
            return notlogs + alllogs

    if expr.is_Mul:
        a = Wild('a')
        x = Wild('x')
        coef = expr.match(a*log(x))
        if coef\
            and (coef[a].is_real\
                or expr.is_Number\
                or expr.is_NumberSymbol\
                or type(coef[a]) in (int, float)\
                or (force\
                and not coef[a].is_imaginary))\
            and (coef[a].func != log\
                or force\
                or (not getattr(coef[a],'is_real')==False\
                    and getattr(x, 'is_positive'))):

            return log(coef[x]**coef[a])
        else:
            return _logcombine(expr.args[0], force)*reduce(lambda x, y:\
             _logcombine(x, force)*_logcombine(y, force),\
             expr.args[1:], 1)

    if expr.is_Function:
        return expr.func(*map(lambda t: _logcombine(t, force), expr.args))

    if expr.is_Pow:
        return _logcombine(expr.args[0], force)**\
        _logcombine(expr.args[1], force)

    return expr
