[app]
title = Kraken Paint
package.name = krakenpaint
package.domain = org.kraken

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas
version = 0.1

# NOTE on requirements:
#   opencv and numpy are the slow/heavy recipes here — expect the first
#   CI build to take a while. sklearn was deliberately removed from
#   simplify_shapes.py (replaced with cv2.kmeans) specifically to avoid
#   needing it as a p4a recipe.
requirements = python3,kivy==2.3.1,pillow,numpy,opencv,plyer

orientation = portrait
fullscreen = 0

# Android file/storage access for the plyer file chooser
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES

android.api = 33
android.minapi = 24
android.ndk = 28c
android.archs = arm64-v8a
android.build_tools = 33.0.2
android.skip_update = False
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
