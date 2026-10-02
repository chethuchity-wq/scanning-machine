# Deploying to the Kolar clinic machine

A step-by-step runbook for installing and running this pipeline on the clinic PC
in Kolar, driven from your machine in Bangalore.

Read **Before you start** fully. Two items there will produce legally wrong
reports or block the install completely if you skip them.

---

## What you are deploying

Three pieces run on the clinic PC in Kolar:

```
  Ultrasound machine  ──DICOM C-STORE (port 4242)──►  Orthanc
                                                        │
                                                        │ REST API (port 8042)
                                                        ▼
                                              pipeline.py watch      (process 1)
                                                        │
                                       writes reports/ + reports/filled/
                                       writes data/app.db
                                                        │
                                                        ▼
                                              webapp (uvicorn, port 8000)
                                                        │              (process 2)
                                                        ▼
                                           doctor's browser / your browser
```

Orthanc is the third piece. It may already be installed at the clinic — check
before installing a second copy.

**Both Python processes must keep running and must restart after a power cut.**
Part F covers that. It is the step most often skipped, and the failure is silent:
scans arrive, no reports are generated, and nobody notices for days.

---

## Before you start

### Blocker 1 — build the release zip

The clinic machine does not need git or GitHub. You send it a zip built from
your last commit. On your machine:

```
cd g:\scanning-machine
git status                      (commit everything first)
deploy\make_release.bat
```

This writes `dist\scanning-machine-<commit>.zip`. It contains only committed
files, so `config_local.py`, `data\`, `reports\` and `.venv` never leave your
machine. Uncommitted changes are **not** included; the script warns you if
there are any.

Copy the zip to the clinic PC — AnyDesk file transfer, a pen drive, or Google
Drive.

### The reporting doctor is set per clinic, on the Settings page

The doctor's name and qualification are printed inside the PCPNDT declaration on
every obstetric report:

> "I, <doctor name> declare that while conducting ultrasonography / image
> scanning on ..., I have neither detected nor disclosed the sex of her foetus to
> anybody in any manner."

This is a statutory declaration under the PCPNDT Act, so the name is **not** in
the code. Each clinic enters its own doctor on the dashboard's **Settings** page
(Part G). Nothing to change in the repository before deploying.

Until a name is entered, reports print a blank line (`____________________`) in
the declaration for the doctor to fill in by hand, and every report is flagged
**needs review** in the worklist with the reason "doctor name not set in
Settings". A missing name is visible; a wrong one is never printed.

Get the exact spelling of the Kolar doctor's name and qualification as they want
it on reports (see the table below).

### Information to collect before you travel

Have all of this written down. Chasing it from Kolar over the phone wastes a trip.

| Item | Where it is used | Who knows it |
|---|---|---|
| Orthanc IP and port | `config_local.py` | clinic IT / whoever installed Orthanc |
| Orthanc username and password | `config_local.py` | same |
| Orthanc AE Title | ultrasound machine config | same |
| Clinic name, address, phone | printed on PDF reports | clinic owner |
| Doctor name + qualification | PCPNDT declaration | clinic owner |
| Default referring doctor | report header | clinic owner |
| Ultrasound machine make/model | DICOM send setup | clinic |
| Windows login password for the PC | everything | clinic |

### Test in Bangalore first

Do a full dry run on your own machine before touching Kolar. You want to hit
problems where you can debug them.

```
cd g:\scanning-machine
run.bat folder "dicom_input"
```

A PDF should appear in `reports\`. Then start the dashboard and confirm the
report shows in the worklist (Part G has the commands).

---

## Part A — Choose how you will reach the machine

You are 70 km away. Assume you will never want to drive there twice for the same
problem. Set up **two independent ways in**, because each fails differently.

**1. Tailscale (primary).** A free mesh VPN. Gives your Bangalore machine a
direct private network connection to the Kolar PC — no port forwarding, works
behind the clinic's router and behind CGNAT. Once connected you can open the
dashboard, reach Orthanc, and run commands as if the machine were on your desk.

**2. AnyDesk or RustDesk (backup).** Remote desktop with unattended access. Use
this when Tailscale itself is the problem, or when you need to see the screen — a
Windows update dialog, a crashed installer.

**Do not port-forward the dashboard to the internet.** It serves patient names
over plain HTTP with no TLS certificate. Over Tailscale the traffic is encrypted
by the VPN. Exposed directly to the internet it is not, and it is also reachable
by anyone who finds the port.

**You also need a human contact at the clinic** with a phone number, who can
physically power cycle the PC. No remote tool survives a machine that is off.

---

## Part B — The one visit you cannot avoid

Installing the remote access tools requires somebody physically at the keyboard,
once. Either drive to Kolar for this, or talk a clinic staff member through it on
a phone call (AnyDesk is the easier one to do by phone — they install it and read
you the 9-digit ID and the password they set).

At the machine:

1. Install Tailscale from https://tailscale.com/download/windows. Sign in with
   the same account you use in Bangalore. In Tailscale's settings enable **Run
   unattended** so it reconnects after a reboot without anyone logging in.
2. Note the machine's Tailscale IP (looks like `100.x.y.z`). Write it down.
3. Install AnyDesk from https://anydesk.com. Open **Settings → Security → Enable
   unattended access** and set a strong password. Note the AnyDesk ID.
4. Set Windows to **never sleep**: Settings → System → Power → Screen and sleep →
   set both sleep options to **Never**. A sleeping PC is an unreachable PC.
5. Check whether a UPS is connected. Kolar power cuts are routine, and an unclean
   shutdown mid-scan is the main cause of corrupted state.

From this point on, everything below can be done from Bangalore.

---

## Part C — Install the prerequisites

Connect over AnyDesk and work on the Kolar machine's desktop.

Python and git do **not** need installing by hand. `setup.bat` (Part D)
downloads and installs Python 3.11 when no 3.11/3.12 is present, and git is not
used at all.

### 1. Orthanc

Check first whether the clinic already has it — a machine that is already sending
DICOM somewhere has an Orthanc or a PACS already.

If not, install from https://www.orthanc-server.com/download.php. After
installing, confirm it answers:

```
curl http://localhost:8042/system
```

**Change the default Orthanc password.** It ships as `orthanc` / `orthanc`, and
that is the account holding all the clinic's patient images. The password lives
in Orthanc's `orthanc.json` configuration file.

### 2. Tesseract (optional)

Only needed if the ultrasound machine burns measurements into the image pixels
instead of sending Structured Reports. The pipeline works without it.

If needed: https://github.com/UB-Mannheim/tesseract/wiki, then set
`TESSERACT_CMD` in `config_local.py` to the installed `tesseract.exe` path.

---

## Part D — Run setup.bat

1. Right-click the zip → **Extract All**. Extract anywhere, e.g. Downloads.
2. Open the extracted `scanning-machine` folder and double-click **setup.bat**.
3. Click **Yes** on the administrator prompt.

It installs to **`C:\scanning-machine`** whichever folder you extracted to — not
under Program Files, not inside OneDrive. Change `INSTALL_DIR` at the top of
`setup.bat` if a clinic needs a different drive.

What it does, in order:

| Step | Detail |
|---|---|
| Stop services | Ends the two scheduled tasks if they are running (matters on updates) |
| Copy files | Copies the program to `C:\scanning-machine`. Never overwrites `config_local.py`, `data\`, `reports\`, `measurements\` or `watch_state.json` |
| Python | Uses an installed Python 3.11/3.12, otherwise downloads and installs 3.11.9 for all users |
| Packages | Creates `.venv` and installs `requirements.txt` (needs internet; a few minutes the first time) |
| Configure | Asks for the Orthanc URL, username and password, clinic name, address and phone, and the healthchecks.io URL, and writes them into `config_local.py`. Tests the Orthanc login immediately and lets you re-enter it if it fails |
| Firewall | Opens port 8000 (dashboard) and, when Orthanc is on this PC, 4242 (DICOM) — to the clinic LAN and Tailscale (`100.64.0.0/10`) only, never the internet |
| Power | Disables sleep and hibernate on mains power |
| Auto-start | Registers the **Ultrasound Pipeline** and **Ultrasound Dashboard** scheduled tasks and starts them (Part F) |
| Finish | Waits for the dashboard to answer, then prints its URLs and the first-login setup token |

Have the information from **Before you start** in front of you when you run it.
Run it again later and it shows the existing config and asks whether to keep it.

---

## Part E — Configuration (done by setup.bat)

`setup.bat` writes `C:\scanning-machine\config_local.py`. To change something
later, either re-run `setup.bat` and answer **n** to "Keep the existing
configuration?", or edit the file in Notepad and restart both tasks. Settings it
does not ask about (such as `TESSERACT_CMD`) can be added to the file by hand —
re-running setup keeps them.

To check Orthanc by hand:

```
cd C:\scanning-machine
run.bat list
```

---

## Part F — Surviving a reboot (done by setup.bat)

Kolar loses power regularly, so this decides whether the deployment actually
works unattended. `setup.bat` creates both tasks like this:

- run **at startup** (1 minute delay, so Orthanc is up first) as **SYSTEM**, so
  nobody needs to log in
- **no time limit** — Task Scheduler's default kills a task after 3 days
- Task Scheduler restarts a failed task, and the wrapper scripts
  `deploy\service_pipeline.bat` / `deploy\service_dashboard.bat` also restart the
  Python process 30 seconds after it exits
- each wrapper first changes into `C:\scanning-machine`. Every path in
  `config.py` is relative; started from `C:\Windows\System32` (Task Scheduler's
  default) the dashboard would open a second, empty database and show no reports
- output goes to `C:\scanning-machine\logs\pipeline.log` and `dashboard.log`

### Then actually test it

Reboot the Kolar machine and confirm both come back on their own. A restart
configuration that has never been tested is not a restart configuration.

```
shutdown /r /t 0
```

Wait three minutes, reconnect, and check the dashboard responds.

### Docker alternative

If the clinic PC has Docker Desktop, `deploy.bat` runs both services with
`restart: unless-stopped`. It puts the dashboard on port **8080** instead of
8000. On a typical clinic Windows PC, Docker Desktop is usually more weight than
it is worth — `setup.bat` is lighter and easier to debug remotely.

---

## Part G — First login to the dashboard

On first start the dashboard has no accounts, and registration is protected by a
setup token so that whoever reaches the page first cannot claim the admin account.

`setup.bat` prints the token at the end. If you missed it, read it from the
file:

```
type C:\scanning-machine\data\setup_token.txt
```

Then open the dashboard:

- On the clinic machine: `http://localhost:8000`
- From Bangalore over Tailscale: `http://100.x.y.z:8000`

Enter the token, choose an admin username and a password of at least 8
characters. The token file is deleted automatically once the account exists.

Then create a separate **staff** account for the clinic's own use, from the
**Users** page, and give them that one. Keep the admin login for yourself — only
admin accounts can add or remove users.

Finally, open **Settings** and fill in the clinic details and the **Reporting
Doctor** section: doctor name, qualification, and the default "Ref by" (used when
the scan carries no referring doctor). Do this before the first real scan — until
the doctor name is set, the page shows a red warning and every Word report is
flagged for review with a blank declaration line.

---

## Part H — Connect the ultrasound machine and verify

### 1. Point the ultrasound machine at Orthanc

On the ultrasound machine's DICOM / network configuration screen, add Orthanc as a
destination:

- AE Title: `ORTHANC` (or whatever Orthanc's configuration specifies)
- IP address: the Kolar PC's **LAN** IP, not the Tailscale IP — the ultrasound
  machine is on the clinic network, not on your VPN
- Port: `4242`

Most ultrasound machines require the vendor's service engineer to change this.
Budget time for it; it is often the longest-lead item in the whole deployment.

Ask the sonographer to **save measurements with calipers during the scan**. The
pipeline reads Structured Reports first, and those are only produced when
measurements are actually saved. Without them it falls back to OCR, which is far
less reliable.

### 2. End-to-end test with a real scan

Do this while you still have the clinic on the phone.

1. Scan a test patient (or re-send an existing study from the machine).
2. Watch the study appear in Orthanc at `http://localhost:8042`.
3. Within about 30 seconds, a PDF should appear in `C:\scanning-machine\reports\`.
4. A `.docx` should appear in `C:\scanning-machine\reports\filled\`.
5. Both should be listed in the dashboard worklist.
6. Open the `.docx` and check: patient name, age, date, clinic name, the doctor's
   name in the declaration, and that the measurement values and their units are
   correct.

**Check the units carefully on the first few reports.** Confirm that a BPD reads
as roughly 9 cms and not 92. If a measurement field is blank and the report is
flagged for review in the worklist, that is the pipeline correctly refusing to
print a value whose unit it could not confirm — note which measurement it was so
the unit can be added.

---

## Part I — Remote monitoring

This is not optional for an unattended machine 70 km away. If the pipeline dies at
9 a.m., you want to know at 9:05, not when the doctor calls three days later
asking where the reports went.

The machine cannot report its own failure — if it loses power or network, it
cannot send you an alert. So it pings an outside service on every poll cycle, and
**that service alerts you when the pings stop**.

1. Sign up free at https://healthchecks.io
2. Create a check. Set its **Period** to 2–3× `POLL_INTERVAL_SECONDS` (default
   10s), so one slow poll does not false-alarm. A period of 1 minute with a 5
   minute grace works well.
3. Set the notification channel to something you will actually see — email,
   Telegram, or SMS.
4. Paste the check's ping URL when `setup.bat` asks for it (or into
   `HEARTBEAT_URL` in `config_local.py`).
5. Restart the pipeline task (or re-run `setup.bat`).
6. Confirm the check turns green in the healthchecks.io dashboard, then stop the
   task and confirm you receive the alert. **Test the alarm**, do not assume it.

---

## Part J — Updating from Bangalore later

Once AnyDesk is up, updates do not need a trip.

1. Commit, then run `deploy\make_release.bat` on your machine.
2. Copy the new zip to the clinic PC over AnyDesk, extract it, and double-click
   `setup.bat`. It stops both tasks, copies the new code over
   `C:\scanning-machine`, installs any new packages and starts the tasks again.
   Answer **Y** to keep the existing configuration.
3. Check the version printed at the top of setup matches your commit, then
   verify with a re-sent study that reports are still generated.

`config_local.py`, `data\`, `reports\` and `watch_state.json` are never
overwritten, so an update never touches the clinic's credentials, database or
generated reports.

**Update during clinic hours only, when someone can tell you if it broke.** A
bad update on a Friday evening means a weekend of no reports. To roll back, run
`setup.bat` from the previous zip, so keep the last one or two.

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| No reports, scans are in Orthanc | Pipeline crashing or task not running | Read `logs\pipeline.log`. In Task Scheduler check **Ultrasound Pipeline** is Running; re-run `setup.bat` to recreate it |
| Dashboard does not load | Dashboard crashing, or firewall rule missing | Read `logs\dashboard.log`; re-run `setup.bat` to recreate the task and firewall rule |
| Dashboard shows no reports, but PDFs exist in `reports\` | Dashboard started from another folder, so it opened a different database | The tasks must run `deploy\service_*.bat`, which change into `C:\scanning-machine`. Re-run `setup.bat` |
| `run.bat list` cannot connect | Wrong Orthanc URL, password, or Orthanc is down | `curl http://localhost:8042/system`, then re-check `config_local.py` |
| Nothing arrives in Orthanc from the machine | Ultrasound DICOM destination wrong, or firewall | Confirm the **LAN** IP and port 4242; allow Orthanc through Windows Firewall |
| Pipeline refuses to start, complains about the watch state file | `watch_state.json` was corrupted by a power cut | Deliberate — starting from zero would regenerate reports over every past study. Follow the recovery steps printed in the error |
| Reports have no measurements | Sonographer is not saving calipers, or no Structured Report | Ask the sonographer to save measurements during the scan |
| `.docx` fields blank, report flagged for review | Measurement units could not be confirmed | Intended safety behaviour. Note which measurement so its unit can be added |
| Dashboard occasionally errors under load | SQLite locking between the two processes | Known issue, see below. Refresh the page |
| Cannot reach the machine at all | Power cut, or Windows update reboot loop | Call the clinic contact and ask them to power cycle |

Useful commands, run from `C:\scanning-machine`:

```
run.bat list                       # is Orthanc reachable?
type data\setup_token.txt          # first-run dashboard token
type VERSION                       # which version is deployed?
type logs\pipeline.log             # what has the pipeline been doing?
```

---

## Known limitations at the time of deployment

Be aware of these. They are open issues, not deployment mistakes.

- **Patient age.** DICOM ages in months or days lose their unit, so a 6-month-old
  prints as "6" and reads as 6 years. Age derived from date of birth can also be
  one year high near a birthday. **Check the age on paediatric and obstetric
  reports before they are signed.**
- **Dashboard timestamps are UTC.** The "Generated" column runs 5 hours 30 minutes
  behind Indian time, so between midnight and 5:30 a.m. it shows the previous
  day's date. Study Date is unaffected.
- **No HTTPS.** Only reach the dashboard over Tailscale or the clinic LAN. Never
  port-forward it.
- **SQLite locking.** The pipeline and dashboard share one database file without
  WAL mode. At clinic volume this is rarely hit, but a page load during a write
  can error. Refreshing works.
- **A failed study is not retried.** If processing fails — for example Orthanc
  restarts mid-download — that study is skipped permanently and only a console
  line records it. If a report is missing for a scan you know arrived, reprocess
  it by hand:

  ```
  run.bat study <orthanc-study-id>
  ```

- **Reports are never overwritten.** Reprocessing the same patient on the same day
  produces `..._2.pdf`, `..._3.pdf`. This is deliberate — it protects a `.docx`
  the doctor has already edited and signed — but it means `reports\` accumulates
  files. Check occasionally that the doctor is opening the newest one.

---

## Deployment checklist

Print this and tick it off.

```
Before travelling
  [ ] Everything committed, deploy\make_release.bat run, zip in hand
  [ ] Kolar doctor's name + qualification (exact spelling) in hand
  [ ] Orthanc IP, port, username, password in hand
  [ ] Clinic name, address, phone in hand
  [ ] Full dry run passed in Bangalore
  [ ] Clinic contact's phone number saved

At the machine (one visit)
  [ ] Tailscale installed, unattended mode on, IP noted
  [ ] AnyDesk installed, unattended access on, ID and password noted
  [ ] UPS checked

Install
  [ ] Orthanc running, default password changed
  [ ] Zip extracted, setup.bat run, Orthanc check passed
  [ ] Admin account created with the setup token, staff account created
  [ ] Doctor name + qualification entered in Settings

Run
  [ ] Machine rebooted and the dashboard came back automatically

Verify
  [ ] Ultrasound machine sends to Orthanc
  [ ] Test scan produced a PDF and a .docx
  [ ] Report shows in the worklist
  [ ] Clinic name, doctor name and units checked on a real report

Monitor
  [ ] healthchecks.io check created and green
  [ ] Alarm tested by stopping the pipeline
  [ ] Handover: clinic staff know the dashboard URL and their login
```
