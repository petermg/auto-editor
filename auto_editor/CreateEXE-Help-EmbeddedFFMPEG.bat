rem pyinstaller --clean __main__.py


pyinstaller --clean --onefile -i icon2.ico -y -n AEGPU.exe --add-data="help.json;auto_editor" --add-binary "ffmpeg.exe;ffmpeg/Windows/" __main__.py

pause