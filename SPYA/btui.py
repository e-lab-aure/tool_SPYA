#!/usr/bin/env python3
import subprocess,os,sys,time,threading,datetime,signal
R='\033[0m';B='\033[1m';G='\033[92m';Y='\033[93m'
C='\033[96m';RED='\033[91m';DIM='\033[2m'
HCI_ROLES={'hci0':'Casque','hci1':'PC'}
REC_DIR='/home/prelude/recordings'
W=54

def run(cmd,timeout=10):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=timeout)
        return r.stdout.strip()
    except:return ''

def clr():os.system('clear')

def get_adapters():
    out=run('hciconfig');adapters={};cur=None
    for line in out.splitlines():
        if line.startswith('hci'):
            cur=line.split(':')[0]
            adapters[cur]={'addr':'','up':False}
        elif cur and 'BD Address:' in line:
            adapters[cur]['addr']=line.split('BD Address:')[1].split()[0]
        elif cur and 'UP' in line:
            adapters[cur]['up']=True
    return adapters

def get_dev_map():
    import os
    AM={"hci0":"A0:AD:9F:73:B7:76","hci1":"A0:AD:9F:73:C5:49"}
    pm={};cm={}
    for hci,amac in AM.items():
        try:
            for e in os.listdir(f"/var/lib/bluetooth/{amac}"):
                if len(e)==17 and e.count(":")==5 and e not in pm:pm[e]=hci
        except:pass
    for hci in AM:
        for l in run(f"hcitool -i {hci} con").splitlines():
            if "ACL" in l:
                p=l.split()
                if len(p)>=3:cm[p[2]]=hci
    return pm,cm

def get_devices():
    pm,cm=get_dev_map()
    out=run("bluetoothctl devices");devices={}
    for line in out.splitlines():
        parts=line.split(" ",2)
        if len(parts)<3:continue
        mac,name=parts[1],parts[2]
        info=run(f"bluetoothctl info {mac}")
        connected=mac in cm
        paired="Paired: yes" in info
        adapter=cm.get(mac,pm.get(mac,"unknown"))
        devices[mac]={"name":name,"connected":connected,"paired":paired,"adapter":adapter}
    return devices

def bl(text=''):
    inner=W-2
    raw=text
    for x in [R,B,G,Y,C,RED,DIM]:raw=raw.replace(x,'')
    pad=max(0,inner-len(raw))
    return f'{C}||{R}{text}{" "*pad}{C}||{R}'.replace('||','║')
def bsep():return f'{C}╠{"═"*W}╣{R}'
def btop():return f'{C}╔{"═"*W}╗{R}'
def bbot():return f'{C}╚{"═"*W}╝{R}'

def draw(devices,adapters,recording,rec_start,msg):
    clr();print(btop())
    print(bl(f'  {B}BT BRIDGE MANAGER{R}   {DIM}PipeWire 1.2.7{R}'))
    print(bsep());print(bl(f' {B}{Y}DONGLES{R}'))
    for hci in sorted(adapters):
        info=adapters[hci];role=HCI_ROLES.get(hci,'?')
        st=f'{G}UP{R}' if info.get('up') else f'{RED}DOWN{R}'
        print(bl(f'  {B}{hci}{R} {info.get("addr","")}  {role}  {st}'))
        hdevs=[d for d in devices.values() if d['adapter']==hci]
        if hdevs:
            for d in hdevs:
                dot=f'{G}●{R}' if d['connected'] else f'{RED}○{R}'
                fl='[conn]' if d['connected'] else '[pair]' if d['paired'] else ''
                print(bl(f'   {dot} {d["name"][:24]:<24} {fl}'))
        else:print(bl(f'   {DIM}(aucun){R}'))
    print(bsep())
    if recording and rec_start:
        e=int(time.time()-rec_start);m,s=divmod(e,60)
        print(bl(f' {RED}{B}⏺  REC  {m:02d}:{s:02d}{R}'))
        print(bsep())
    print(bl(f' {B}[1]{R} Connecter un peripherique'))
    print(bl(f' {B}[2]{R} Visible PC         (hci1)'))
    print(bl(f' {B}[3]{R} Appairer casque    (hci0)'))
    print(bl(f' {B}[4]{R} Scanner nouveaux appareils'))
    print(bl(f' {B}[5]{R} Deconnecter un peripherique'))
    if recording:
        print(bl(f' {RED}{B}[6] STOP enregistrement{R}'))
    else:
        print(bl(f' {B}[6]{R} Demarrer enregistrement'))
    print(bl(f' {B}[l]{R} Lister enregistrements'))
    print(bl(f' {B}[r]{R} Actualiser   {B}[q]{R} Quitter'))
    if msg:
        print(bsep())
        for chunk in [msg[i:i+W-4] for i in range(0,len(msg),W-4)]:
            print(bl(f' {Y}{chunk}{R}'))
    print(bbot());print()

def action_connect():
    out=run('bluetoothctl devices');devs=[]
    for line in out.splitlines():
        p=line.split(' ',2)
        if len(p)>=3:devs.append((p[1],p[2]))
    if not devs:return 'Aucun peripherique connu.'
    print(btop())
    for i,(m,n) in enumerate(devs):print(bl(f' {B}[{i+1}]{R} {n} {DIM}{m}{R}'))
    print(bl(f' {B}[0]{R} Annuler'));print(bbot())
    ch=input(' Choix: ').strip()
    if not ch.isdigit() or int(ch)==0:return ''
    idx=int(ch)-1
    if idx>=len(devs):return 'Choix invalide.'
    mac,name=devs[idx]
    print(f' Connexion {name}...')
    r=run(f'bluetoothctl connect {mac}',timeout=20)
    if 'success' in r.lower():return f'Connecte: {name}'
    return f'Echec connexion: {name}'

def action_disconnect():
    out=run('bluetoothctl devices');devs=[]
    for line in out.splitlines():
        p=line.split(' ',2)
        if len(p)>=3:
            m=p[1];n=p[2]
            info=run(f'bluetoothctl info {m}')
            if 'Connected: yes' in info:devs.append((m,n))
    if not devs:return 'Aucun peripherique connecte.'
    print(btop())
    for i,(m,n) in enumerate(devs):print(bl(f' {B}[{i+1}]{R} {n} {DIM}{m}{R}'))
    print(bl(f' {B}[0]{R} Annuler'));print(bbot())
    ch=input(' Choix: ').strip()
    if not ch.isdigit() or int(ch)==0:return ''
    idx=int(ch)-1
    if idx>=len(devs):return 'Choix invalide.'
    mac,name=devs[idx]
    r=run(f'bluetoothctl disconnect {mac}',timeout=10)
    if 'success' in r.lower():return f'Deconnecte: {name}'
    return f'Echec: {name}'

def action_visible_pc():
    run('hciconfig hci1 piscan')
    return 'hci1 (PC) visible 60s - cherchez RPI-PC depuis Windows'

def action_pair_headset():
    print(" Mettez le Jabra en mode pairing, scan 15s...")
    import subprocess as sp
    p2=sp.Popen(["bluetoothctl"],stdin=sp.PIPE,stdout=sp.PIPE,stderr=sp.PIPE,text=True)
    p2.stdin.write("select A0:AD:9F:73:B7:76\nagent on\nscan on\n");p2.stdin.flush()
    time.sleep(15)
    p2.stdin.write("scan off\nquit\n");p2.stdin.flush()
    p2.wait(timeout=5)
    pm2,_=get_dev_map()
    phci0={m for m,h in pm2.items() if h=="hci0"}
    out=run("bluetoothctl devices");devs=[]
    for line in out.splitlines():
        p=line.split(" ",2)
        if len(p)>=3 and p[1] not in phci0:devs.append((p[1],p[2]))
    if not devs:
        for line in out.splitlines():
            p=line.split(" ",2)
            if len(p)>=3:devs.append((p[1],p[2]))
    if not devs:return "Aucun appareil trouve."
    print(btop())
    ch=input(" Choix (0=annuler): ").strip()
    if not ch.isdigit() or int(ch)==0:return ""
    idx=int(ch)-1
    if idx>=len(devs):return "Choix invalide."
    mac,name=devs[idx]
    run(f"bluetoothctl pair {mac}",timeout=20)
    run(f"bluetoothctl trust {mac}",timeout=10)
    r=run(f"bluetoothctl connect {mac}",timeout=20)
    if "success" in r.lower():return f"Appaire: {name}"
    return f"Tente: {name}"

def action_scan():
    print(' Scan 10s...')
    out=run('bluetoothctl -- scan on & sleep 10 ; bluetoothctl devices',timeout=20)
    found=[]
    for line in out.splitlines():
        p=line.split(' ',2)
        if len(p)>=3:found.append(f'{p[2]} {p[1]}')
    return ('\n'.join(found[:8])) if found else 'Aucun appareil trouve.'

def get_bt_sources():
    out=run('pactl list sources short')
    mic=None;mon=None
    for l in out.splitlines():
        if 'bluez' in l and 'monitor' not in l:mic=l.split()[1]
        if 'bluez' in l and 'monitor' in l:mon=l.split()[1]
    return mic,mon

def get_src_fmt(s):
    out=run("pactl list sources short")
    for l in out.splitlines():
        if s in l:
            try:
                p=l.split()
                ch=int([x for x in p if x.endswith("ch")][0][:-2])
                hz=int([x for x in p if x.endswith("Hz")][0][:-2])
                return hz,ch
            except:pass
    return 48000,2

def start_recording():
    global rec_procs
    os.makedirs(REC_DIR,exist_ok=True)
    mic_src,mon_src=get_bt_sources()
    if not mon_src:return False,"Aucune source BT trouvee."
    ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    mf=f"/tmp/mic_{ts}.wav";sf=f"/tmp/spk_{ts}.wav"
    out=f"{REC_DIR}/rec_{ts}.wav"
    if mic_src:
        mr,mc=get_src_fmt(mic_src)
        pm=subprocess.Popen(
            f'pw-record --target={mic_src} --rate={mr} --channels={mc} {mf}',
            shell=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    else:
        open(mf,"wb").close();pm=None
    sr,sc=get_src_fmt(mon_src)
    ps=subprocess.Popen(
        f'pw-record --target={mon_src} --rate={sr} --channels={sc} {sf}',
        shell=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    rec_procs=[pm,ps,mf,sf,out]
    return True,ts

def stop_recording():
    global rec_procs
    if not rec_procs:return "Pas d enregistrement actif."
    pm,ps,mf,sf,out=rec_procs
    rec_procs=[]
    for p in [pm,ps]:
        if p:
            try:p.terminate();p.wait(timeout=3)
            except:pass
    import threading
    def _finalize(mf,sf,out):
        import struct,shutil
        def fix_wav(fn):
            s=os.path.getsize(fn)
            if s<44:return
            with open(fn,"r+b") as f:
                f.seek(4);f.write(struct.pack("<I",s-8))
                f.seek(40);f.write(struct.pack("<I",s-44))
        time.sleep(1)
        for fx2 in [mf,sf]:
            if os.path.exists(fx2):fix_wav(fx2)
        sz=os.path.getsize(mf) if os.path.exists(mf) else 0
        if sz>44:
            run(f"sox -m {mf} {sf} {out}",timeout=300)
        else:
            shutil.copy2(sf,out)
        for fx in [mf,sf]:
            try:os.remove(fx)
            except:pass
    threading.Thread(target=_finalize,args=(mf,sf,out),daemon=True).start()
    return f"Arret enreg — finalisation: {os.path.basename(out)}"

def list_recordings():
    os.makedirs(REC_DIR,exist_ok=True)
    files=sorted(os.listdir(REC_DIR))
    if not files:return 'Aucun enregistrement.'
    return '\n'.join(files[-10:])

def main():
    msg='';rec=False;rs=None
    signal.signal(signal.SIGINT,lambda s,f:sys.exit(0))
    while True:
        draw(get_devices(),get_adapters(),rec,rs,msg);msg=''
        try:
            import termios,sys
            termios.tcflush(sys.stdin,termios.TCIFLUSH)
        except:pass
        ch=input(' > ').strip().lower()
        if ch=='q':
            if rec:stop_recording()
            clr();sys.exit(0)
        elif ch=='1':msg=action_connect()
        elif ch=='2':msg=action_visible_pc()
        elif ch=='3':msg=action_pair_headset()
        elif ch=='4':msg=action_scan()
        elif ch=='5':msg=action_disconnect()
        elif ch=='6':
            if rec:msg=stop_recording();rec=False;rs=None
            else:
                ok,ts=start_recording()
                rec=ok;rs=time.time() if ok else None
        elif ch=='l':
            clr();print(btop())
            for ln in list_recordings().splitlines():print(bl(f' {ln}'))
            print(bbot());input(' [Entree]...')

if __name__=='__main__':main()
