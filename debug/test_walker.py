import uiautomation as auto
try:
    walker = auto.GetRawViewWalker()
    print("GetRawViewWalker() exists")
except AttributeError:
    print("GetRawViewWalker() does not exist")

try:
    walker = auto.RawViewWalker
    print("RawViewWalker property exists")
except AttributeError:
    print("RawViewWalker property does not exist")
