# PDF Redactor

Take information out of a PDF. Click a word or drag a box, pick a color, and save a copy. The original file stays as it is.

A redaction deletes the text underneath it. The word cannot be copied out, searched, or brought back by removing the block. A box also erases the part of a picture it covers, which is how scanned pages are handled.

<p align="center">
  <img src="docs/images/one-pager.png" alt="One-page sheet for PDF Redactor on Windows. It explains that the app takes names, numbers, and other private details out of a PDF, that PDFRedactor.exe is a standalone program with nothing to install, and it shows an invoice with black redaction blocks. The steps are: click a word, drag a box, and redact every copy. The footer covers color, undo, and saving a copy." width="640">
</p>

## Use it

1. Open a PDF, or drop one on the window.
2. **Click a word** redacts that whole word. If the same word appears again, choose **Redact them all**.
3. **Drag a box** covers a region. Use this for a signature, a photo, or a scan.
4. Pick a block color before you redact. Black is the default. White still removes the text.
5. Every redacted string is listed with **Undo** and **Redact all**. Undo takes that string back. Redact all covers every copy still in the file.
6. **Save a copy**. The new file is named with `-redacted` on the end.

Arrow keys turn the page. Ctrl+O opens a file. Ctrl+S saves a copy. Escape closes the “redact every copy” prompt.

Password-protected PDFs are not opened. Text that exists only as part of a picture has no word to click; drag a box over it and that part of the picture is erased.

The window talks only to your own computer. The PDF is not uploaded.

## Download the Windows app

This is the file to use on a Windows computer. It is one program, `PDFRedactor.exe`, about 33 MB. Opening it starts the app. There is no installer, no setup wizard, and the computer does not need Python.

You need Windows 10 or Windows 11, a web browser, and a GitHub account that has been allowed to see this repository. The repository is private, so the download page is visible only while you are signed in with that account.

1. Open your browser and go to [github.com/login](https://github.com/login). Sign in.
2. Open the [releases page](https://github.com/regenerous/pdf-redactor/releases).
3. If the page says **404**, the account you signed in with cannot see this repository. Sign in with the account that was given access, then open the link again.
4. The newest release is the first one on the page. Its heading looks like **PDF Redactor v1.0.3**. That is the current release.
5. Under that heading, find **Assets**. If the file names are hidden, click **Assets** to open the list.
6. Click **PDFRedactor.exe**.

The same file is always at this address, which points at whatever the newest release is:

[https://github.com/regenerous/pdf-redactor/releases/latest/download/PDFRedactor.exe](https://github.com/regenerous/pdf-redactor/releases/latest/download/PDFRedactor.exe)

The browser saves the file in your **Downloads** folder.

### If the browser holds the file back

Chrome and Edge sometimes pause a program they have rarely seen. The file on the releases page is the app.

In **Chrome**, look at the download bar at the bottom of the window, or press Ctrl+J to open Downloads. Next to `PDFRedactor.exe`, open the small menu and choose **Keep**. If a second question appears, choose **Download anyway** or **Keep anyway**.

In **Edge**, open Downloads (Ctrl+J). If the line says the file was blocked, click the three dots on that line, choose **Keep**, and then **Keep anyway**.

### Open it

1. Click the folder icon on the taskbar to open File Explorer.
2. In the left sidebar, click **Downloads**.
3. Double-click **PDFRedactor.exe**.

Windows may show a blue window titled **Windows protected your PC**, with the publisher listed as unknown. That appears because Windows has not seen this program before.

1. Click **More info**.
2. Click **Run anyway**.

The app window opens. The title starts with **PDF Redactor**. The first open can take a few seconds.

You can leave the file in Downloads, or move it. To move it, right-click `PDFRedactor.exe`, choose **Cut**, open the Desktop, right-click an empty spot, and choose **Paste**. Double-click the file in its new place. The file is the whole app. It keeps working if you put it on a USB drive and open it on another Windows 10 or Windows 11 computer.

Close the app with the X in the corner of its window.

If a message says the **WebView2** runtime is missing, or the window never appears, install it and try again. Open [the WebView2 download page](https://developer.microsoft.com/microsoft-edge/webview2/), and under **Evergreen Standalone Installer** download the **x64** installer. Double-click that installer and accept the steps. Then double-click `PDFRedactor.exe` again. Windows 11 already includes this piece, and most Windows 10 computers have it because Microsoft Edge is installed.

## Build it from source

Building is how you make `PDFRedactor.exe` yourself from this project’s files. You only need to do this if you want to build the program. The download above is the same app, already built.

The build runs on Windows. Python is needed on the computer that does the building. After the build finishes, `PDFRedactor.exe` runs on its own, and that copy can be moved to a computer that does not have Python.

Plan on an internet connection for the download and for the build. The build usually takes several minutes. Leave the window open until it says it is finished.

### 1. Install Python

Install **Python 3.12.10**. That is the Python version this project is built with, and it is the last 3.12 release that includes a Windows installer.

1. Open [the Python 3.12.10 release page](https://www.python.org/downloads/release/python-31210/).
2. Scroll down to the **Files** table.
3. Click **Windows installer (64-bit)**. The file is named `python-3.12.10-amd64.exe`.

Almost every Windows 10 and Windows 11 computer is 64-bit. To check: press the Windows key, type `settings`, and open **Settings**. Go to **System**, then **About**. Read **System type**. If it says **64-bit operating system**, you clicked the right installer. If it says **32-bit operating system**, go back to the Files table and click **Windows installer (32-bit)** instead.

1. When the download finishes, open your **Downloads** folder and double-click `python-3.12.10-amd64.exe`.
2. If Windows asks whether to allow the app to make changes, click **Yes**.
3. On the first screen of the installer, look at the bottom. Check the box labeled **Add python.exe to PATH**. That box starts unchecked. The build cannot find Python until it is checked.
4. Leave the other choices as they are, and click **Install Now**.
5. Wait until the window says the setup was successful, then click **Close**.

### 2. Download the project

1. Stay signed in to GitHub and open [the project page](https://github.com/regenerous/pdf-redactor).
2. Click the green **Code** button.
3. Click **Download ZIP**.
4. Open **Downloads** and find `pdf-redactor-main.zip`.
5. Right-click the zip file and choose **Extract All**.
6. Click **Extract**. Leave the folder destination as Windows suggests.

You now have a normal folder named `pdf-redactor-main` next to the zip file. Open that folder. You should see `launch.py`, `README.md`, `requirements.txt`, and folders named `redactor`, `samples`, and `scripts`.

Use this extracted folder for the rest of the steps. A zip that is still closed, or a File Explorer window whose address bar ends in `.zip`, is the archive itself. Commands in the next step need the extracted folder.

### 3. Open a command window in that folder

1. Open the extracted `pdf-redactor-main` folder in File Explorer, so you can see `launch.py`.
2. Click the address bar once. The folder path becomes text you can replace.
3. Type `powershell` and press Enter.

A window with a dark blue background opens. This is PowerShell. It is already inside the project folder. The last line ends with a blinking cursor. That is where you type.

Check the location by typing this and pressing Enter:

```powershell
dir
```

The list should include `launch.py`, `requirements.txt`, and `scripts`. If those names are missing, close the window, open the extracted folder (the one that contains `launch.py`), and start PowerShell from its address bar again.

### 4. Check that Python is visible

Type this and press Enter:

```powershell
python --version
```

A successful result looks like `Python 3.12.10`.

If a message says Python was not found, or the Microsoft Store opens:

1. Close the Store.
2. Open **Settings**.
3. Go to **Apps**, then **Advanced app settings**, then **App execution aliases**. On Windows 10 the path is **Apps**, then **Apps & features**, then **App execution aliases**.
4. Turn off the switches for `python.exe` and `python3.exe`.
5. Close the PowerShell window. Open a new one from the project folder’s address bar, as in the previous step. A window that was already open does not notice a new install.
6. Run `python --version` again.

If it still fails, run `python-3.12.10-amd64.exe` from Downloads again. Choose **Modify**, confirm **Add python.exe to PATH** is checked, finish the installer, then open a new PowerShell window and try `python --version` once more.

### 5. Build the exe

Copy this whole line into PowerShell and press Enter:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

That line runs the project’s build script. `ExecutionPolicy Bypass` applies only to this one run, so Windows will allow the script. You do not change a system setting.

The script then does four things, and prints a lot of text while it does them:

1. It creates a folder named `.venv` inside the project. That folder holds a private copy of Python for this project.
2. It downloads the libraries the app needs.
3. It packs the app, its icon, and those libraries into one file.
4. It writes `dist\PDFRedactor.exe`.

Scrolling text, including lines that say `INFO`, is normal. Wait until new text stops and you get the cursor back. A finished build prints two lines like these, with your own user name and folders in the path:

```text
Portable app: C:\Users\YourName\Downloads\pdf-redactor-main\dist\PDFRedactor.exe
Copy that file anywhere and double-click it. Nothing else needs to be installed.
```

The build can be started again with the same command if it stops early. It reuses the `.venv` folder it already made.

### 6. Start the file you built

1. In File Explorer, open the project folder, then open the `dist` folder.
2. Double-click `PDFRedactor.exe`.
3. If Windows shows **Windows protected your PC**, click **More info**, then **Run anyway**.

The window that opens is the app. You can copy `dist\PDFRedactor.exe` to the Desktop or anywhere else and open it from there. After that, the project folder is only needed if you want to build again.

`samples\sample-form.pdf` is a made-up invoice in the project folder. You can open it in the app to practice. The number `472-19-8831` appears more than once, so you can try **Redact them all**.

### If the build stops

Read the last lines in the PowerShell window. They name the problem.

**Python was not found**, or the script says to install Python and check **Add python.exe to PATH**. Close PowerShell, finish the Python steps above, open a new PowerShell window in the project folder, and run the build command again.

**The script path is not recognized**, or a message says it cannot find `.\scripts\build_windows.ps1`. PowerShell is in the wrong folder. Run `dir`. When the list includes `launch.py` and `scripts`, run the build command again.

**A connection, timeout, or name-resolution error** while text mentions `pip`. The computer could not reach the internet, or the connection dropped. Check the network and run the same build command again.

**`dist\PDFRedactor.exe` is missing** even though the script said the build finished. Windows Security sometimes removes a newly built program. Open **Windows Security**, then **Virus & threat protection**, then **Protection history**. If `PDFRedactor.exe` is listed there, choose the action that allows it, then run the build command again.

**The exe is there, and double-clicking it does nothing or asks for WebView2.** Install the WebView2 runtime from the link in the download section, then double-click the exe again.

### Run the source code without making an exe

This opens the app from the project files. It is useful on a Mac or Linux computer, where the `.exe` build does not apply, and on Windows if you want to try the app before the build.

The commands below use the project’s private Python in `.venv`, so you can paste them without learning how to “activate” a virtual environment.

**Windows.** Open PowerShell in the extracted folder, as above, with `python --version` already showing Python 3.12. Paste one line at a time, and wait for the cursor to come back before the next line.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-windows.txt
.\.venv\Scripts\python.exe -m redactor
```

The last command opens the app’s own window. Leave PowerShell open while you use the app. To stop the app, click the PowerShell window and press Ctrl+C.

To open a browser tab instead of the app window, use this as the last command:

```powershell
.\.venv\Scripts\python.exe -m redactor --browser
```

**Mac.** Install Python 3.12.10 from the same [release page](https://www.python.org/downloads/release/python-31210/): in the Files table, click the **macOS 64-bit universal2 installer** and run it. Then open **Terminal** (press Command+Space, type `Terminal`, and press Return).

In Terminal, go into the extracted folder. If it is in Downloads, this is the command, followed by Return:

```bash
cd ~/Downloads/pdf-redactor-main
```

If `ls` does not list `launch.py`, the folder is somewhere else. In Finder, open the extracted folder, then look at the path bar. You can also drag the folder onto the Terminal window after typing `cd ` (with a space) and press Return.

Then paste one line at a time:

```bash
python3 --version
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m redactor --browser
```

`python3 --version` should print `Python 3.12.10`, or another 3.12 version. The last command opens the app in your browser. Leave Terminal open. Press Control+C in Terminal when you want to stop it.

**Linux.** Open a terminal in the extracted folder. If `python3 --version` prints 3.12 or newer, continue. If the command is missing, install Python 3.12 from your system’s package tool first. On Ubuntu, this is:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

Then, from the extracted folder:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m redactor --browser
```

Stop it with Ctrl+C.

### Optional: run the tests

Tests check the redaction engine. From the project folder, after the `.venv` folder exists:

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Mac or Linux:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
./.venv/bin/python -m pytest
```

The last lines include a count of tests and the word `passed`.
