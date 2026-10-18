#!/bin/bash
# usage: texts.sh  -> prints bounds + text/desc of all labelled nodes from a fresh uiautomator dump
source ~/android-ref-lab/env.sh
adb shell uiautomator dump /sdcard/w.xml >/dev/null 2>&1
adb exec-out cat /sdcard/w.xml | python3 -c "
import sys,xml.etree.ElementTree as E
for e in E.fromstring(sys.stdin.read()).iter('node'):
  t=e.get('text') or e.get('content-desc')
  b=e.get('bounds')
  if t and b!='[0,0][0,0]': print(b,repr(t[:90]))
"
