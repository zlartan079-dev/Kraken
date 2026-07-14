"""
core/turtle_stub.py
--------------------
Real turtle.Turtle()/turtle.Screen() need tkinter under the hood, which
isn't available under python-for-android. In pv.py the turtle calls only
trace an on-screen outline preview — the actual saved PNG is produced by
ImagePolygonDrawerPurePIL (polygon_render.py) from the registered polygon
data. finalize_and_save() doesn't touch the screen object it's handed,
so these stand-ins just need to swallow every call pv.py's body makes
without erroring, and don't need to draw anything.
"""


class TurtleStub:
    def __init__(self):
        self._pos = (0, 0)

    def pensize(self, *a, **kw):
        pass

    def penup(self):
        pass

    def pendown(self):
        pass

    def goto(self, x, y=None):
        self._pos = (x, y) if y is not None else x

    def pencolor(self, *a, **kw):
        pass

    def fillcolor(self, *a, **kw):
        pass

    def begin_fill(self):
        pass

    def end_fill(self):
        pass

    def forward(self, *a, **kw):
        pass

    def left(self, *a, **kw):
        pass

    def right(self, *a, **kw):
        pass

    def position(self):
        return self._pos


class ScreenStub:
    def colormode(self, *a, **kw):
        pass

    def setup(self, *a, **kw):
        pass

    def bgcolor(self, *a, **kw):
        pass

    def tracer(self, *a, **kw):
        pass

    def setworldcoordinates(self, *a, **kw):
        pass

    def update(self):
        pass
