import os, paramiko, dash, json, time, re
from dash import dcc, html, Input, Output, State, ALL, callback_context, no_update
import dash_bootstrap_components as dbc
from concurrent.futures import ThreadPoolExecutor
from win10toast import ToastNotifier
from datetime import datetime

# --- CONFIG ---
JSON_FILE = "servers.json"
DEFAULT_SSH_KEY = os.path.join(os.environ.get('USERPROFILE', os.environ.get('HOME', '')), ".ssh", "id_xxxx")
last_net_stats = {}
last_online_time = {}
toaster = ToastNotifier()

def load_servers():
    if not os.path.exists(JSON_FILE):
        with open(JSON_FILE, "w") as f: json.dump([], f)
        return []
    try:
        with open(JSON_FILE, "r") as f:
            data = json.load(f)
            for s in data:
                if "alerts" not in s:
                    s["alerts"] = {"cpu": 90, "temp": 75, "ram": 85, "disk": 90, "offline_sec": 30}
            return data
    except Exception: return []

def save_servers(servers):
    try:
        with open(JSON_FILE, "w") as f: json.dump(servers, f, indent=4)
    except Exception as e: print(f"Save Error: {e}")

def trigger_alert(server_name, msg):
    try: toaster.show_toast(f"ARCCat Alert: {server_name}", msg, duration=5, threaded=True)
    except: pass

def get_ssh_key(key_path):
    if not key_path or not os.path.exists(key_path): return None
    try: return paramiko.Ed25519Key.from_private_key_file(key_path)
    except:
        try: return paramiko.RSAKey.from_private_key_file(key_path)
        except: return None

# --- HELPERS ---
def fmt_speed(b_s):
    if b_s < 1024: return f"{int(b_s)} B/s"
    return f"{round(b_s/1024, 1)} KB/s" if b_s < 1024**2 else f"{round(b_s/1024**2, 1)} MB/s"

def fmt_bytes(b):
    if b < 1024**2: return f"{round(b/1024, 1)} KB"
    if b < 1024**3: return f"{round(b/1024**2, 1)} MB"
    return f"{round(b/1024**3, 1)} GB"

def get_duration_str(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0: return f"{days}g {hours}s {minutes}dk"
    if hours > 0: return f"{hours}s {minutes}dk"
    return f"{minutes}dk {seconds}sn"

# --- SSH FETCH ENGINE ---
def fetch_single_server(s):
    global last_net_stats, last_online_time
    sid = str(s['id'])
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    al = s.get("alerts", {})
    
    try:
        key_path = s.get('ssh_key') or DEFAULT_SSH_KEY
        key = get_ssh_key(key_path)
        ssh.connect(s['ip'], username=s['user'], pkey=key, timeout=5, banner_timeout=10)
        last_online_time[sid] = time.time()
        
        cmds = [
            "echo CPU:$(top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | head -n 1)",
            "echo TMP:$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)",
            "echo MEM:$(free -m | awk '/Mem:/ {print $2 \" \" $3}')",
            "echo SWP:$(free -m | awk '/Swap:/ {print $2 \" \" $3}')",
            "echo DSK:$(df -m / | tail -1 | awk '{print $2 \" \" $3}')",
            "echo NET:$(cat /proc/net/dev | grep -vE 'lo|face|Inter' | awk '{rx+=$2; tx+=$10} END {print rx \" \" tx}')",
            "echo LOD:$(awk '{print $1}' /proc/loadavg)",
            "echo OS:$(grep 'PRETTY_NAME' /etc/os-release | cut -d'\"' -f2 | head -n 1)",
            "echo UPT:$(uptime -p)"
        ]
        
        stdin, stdout, stderr = ssh.exec_command("; ".join(cmds))
        raw = stdout.read().decode('utf-8', errors='ignore')
        ssh.close()
        
        p = {line.split(":")[0]: line.split(":")[1].strip() for line in raw.splitlines() if ":" in line}
        def safe_split(key, idx):
            try: return p.get(key, "").split()[idx]
            except: return "0"

        cpu_v = float(p.get("CPU", "0").replace(',', '.'))
        temp_v = round(int(p.get("TMP", "0"))/1000, 1) if p.get("TMP","0").isdigit() else 0
        m_t, m_u = float(safe_split("MEM", 0)), float(safe_split("MEM", 1))
        s_t, s_u = float(safe_split("SWP", 0)), float(safe_split("SWP", 1))
        d_t, d_u = float(safe_split("DSK", 0)), float(safe_split("DSK", 1))
        rx_total, tx_total = float(safe_split("NET", 0)), float(safe_split("NET", 1))
        
        now = time.time()
        rx_speed, tx_speed = 0.0, 0.0
        if sid in last_net_stats:
            prev = last_net_stats[sid]
            dt = now - prev['time']
            if dt > 0: rx_speed, tx_speed = (rx_total - prev['rx']) / dt, (tx_total - prev['tx']) / dt
        last_net_stats[sid] = {'rx': rx_total, 'tx': tx_total, 'time': now}
        
        ram_p = round((m_u/m_t)*100, 1) if m_t > 0 else 0
        swp_p = round((s_u/s_t)*100, 1) if s_t > 0 else 0
        dsk_p = round((d_u/d_t)*100, 1) if d_t > 0 else 0

        if cpu_v > al.get('cpu', 100): trigger_alert(s['name'], f"CPU: %{cpu_v}")
        if ram_p > al.get('ram', 100): trigger_alert(s['name'], f"RAM: %{ram_p}")

        return {
            "id": s['id'], "status": "Online", "os": p.get("OS", "Linux"),
            "cpu": cpu_v, "temp": temp_v, "mem_p": ram_p, "mem_v": f"{int(m_u)}/{int(m_t)} MB",
            "swp_p": swp_p, "swp_v": f"{int(s_u)}/{int(s_t)} MB",
            "disk_p": dsk_p, "disk_v": f"{round(d_u/1024, 1)}/{round(d_t/1024, 1)} GB",
            "net_instant": f"↓ {fmt_speed(rx_speed)} ↑ {fmt_speed(tx_speed)}",
            "net_total": f"Total: ↓ {fmt_bytes(rx_total)} | ↑ {fmt_bytes(tx_total)}",
            "upt": p.get("UPT", "N/A")
        }
    except Exception as e:
        if ssh: ssh.close()
        last_seen_ts = last_online_time.get(sid)
        off_info = "Offline"
        if last_seen_ts:
            elapsed = time.time() - last_seen_ts
            last_dt = datetime.fromtimestamp(last_seen_ts).strftime('%H:%M:%S')
            off_info = f"Offline (Son: {last_dt}, {get_duration_str(elapsed)} önce)"
            if elapsed > al.get('offline_sec', 30): trigger_alert(s['name'], "OFFLINE!")
        
        return {"id": s['id'], "status": off_info}

# --- UI ---
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY], suppress_callback_exceptions=True)

app.layout = html.Div(style={"backgroundColor": "#000", "minHeight": "100vh", "padding": "25px"}, children=[
    dcc.Interval(id='global-timer', interval=10000, n_intervals=0),
    dcc.Store(id='edit-id-store', data=None),
    dbc.Container([
        html.Div([
            html.H2("ARCCat Master", style={"fontWeight":"900", "color":"#007aff"}),
            html.Div(id="last-sync", style={"fontSize":"11px", "color":"#444"})
        ], className="text-center mb-4"),
        dbc.Tabs([
            dbc.Tab(label="SYSTEMS", tab_id="tab-dash"),
            dbc.Tab(label="ALERTS", tab_id="tab-alerts"),
            dbc.Tab(label="CONFIG", tab_id="tab-mgmt")
        ], id="tabs-nav", active_tab="tab-dash", className="mb-4"),
        html.Div(id="tab-display")
    ], fluid=True)
])

@app.callback(
    [Output("tab-display", "children"), Output("last-sync", "children")],
    [Input("tabs-nav", "active_tab")]
)
def render_base_layout(active_tab):
    servers = load_servers()
    sync_text = f"Sync: {time.strftime('%H:%M:%S')}"
    
    if active_tab == "tab-dash":
        cards = [dbc.Col(dbc.Card(dbc.CardBody([
            html.Div([html.B(s['name']), html.Small(id={"type":"os-text","index":s['id']}, style={"display":"block","color":"#007aff"})]),
            html.Div(id={"type":"card-content","index":s['id']}, children="Loading...")
        ]), style={"backgroundColor":"#0c0c0c","border":"1px solid #222","borderRadius":"18px","minHeight":"200px"}), md=3, className="mb-3") for s in servers]
        return dbc.Row(cards), sync_text

    elif active_tab == "tab-alerts":
        rows = [html.Tr([
            html.Td(s['name']),
            html.Td(dbc.Input(type="number", value=s.get("alerts",{}).get('offline_sec', 30), id={"type":"in-off", "index":s['id']}, size="sm")),
            html.Td(dbc.Input(type="number", value=s.get("alerts",{}).get('cpu', 90), id={"type":"in-cpu", "index":s['id']}, size="sm")),
            html.Td(dbc.Input(type="number", value=s.get("alerts",{}).get('ram', 85), id={"type":"in-ram", "index":s['id']}, size="sm")),
            html.Td(dbc.Input(type="number", value=s.get("alerts",{}).get('disk', 90), id={"type":"in-disk", "index":s['id']}, size="sm")),
            html.Td(dbc.Button("GÜNCELLE", id={"type":"btn-al-save", "index":s['id']}, color="primary", size="sm"))
        ]) for s in servers]
        return dbc.Table([html.Thead(html.Tr([html.Th("Sunucu"), html.Th("Offline (s)"), html.Th("CPU %"), html.Th("RAM %"), html.Th("Disk %"), html.Th("İşlem")])), html.Tbody(rows)], color="dark", bordered=True), sync_text

    else: # CONFIG
        rows = [html.Tr([html.Td(s['name']), html.Td(s['ip']), html.Td(s['user']), html.Td(dbc.ButtonGroup([dbc.Button("EDİT", id={"type":"edit-btn", "index":s['id']}, color="warning", size="sm"), dbc.Button("SİL", id={"type":"del-btn", "index":s['id']}, color="danger", size="sm")]))]) for s in servers]
        return dbc.Container([dbc.Card(dbc.CardBody([dbc.Row([dbc.Col(dbc.Input(id="add-name", placeholder="İsim")), dbc.Col(dbc.Input(id="add-ip", placeholder="IP")), dbc.Col(dbc.Input(id="add-user", placeholder="User"))], className="g-2 mb-2"), dbc.Row([dbc.Col(dbc.Input(id="add-key", placeholder="Key Path")), dbc.Col(dbc.Button("KAYDET", id="save-btn", color="primary", className="w-100"))], className="g-2")]), style={"backgroundColor":"#111","marginBottom":"20px"}), dbc.Table([html.Thead(html.Tr([html.Th("Ad"), html.Th("IP"), html.Th("User"), html.Th("Aksiyon")])), html.Tbody(rows)], color="dark", bordered=True)]), sync_text

@app.callback(
    [Output({"type":"card-content","index":ALL}, "children"),
     Output({"type":"os-text","index":ALL}, "children")],
    [Input("global-timer", "n_intervals"), Input("tabs-nav", "active_tab")],
    [State({"type":"card-content","index":ALL}, "id")],
    prevent_initial_call=True
)
def refresh_dashboard_data(n, active_tab, card_ids):
    if active_tab != "tab-dash": return [no_update]*len(card_ids), [no_update]*len(card_ids)
    
    servers = load_servers()
    with ThreadPoolExecutor(max_workers=min(len(servers)+1, 15)) as exe:
        results = list(exe.map(fetch_single_server, servers))
    
    res_map = {str(r['id']): r for r in results}
    contents, os_labels = [], []

    def get_color(v): return "danger" if v > 85 else "warning" if v > 70 else "success"

    for cid in card_ids:
        sid = str(cid['index'])
        d = res_map.get(sid)
        if not d or "Online" not in d.get('status', ''):
            contents.append(html.Div(d['status'] if d else "N/A", className="text-danger small mt-4", style={"textAlign":"center"}))
            os_labels.append("")
        else:
            contents.append(html.Div([
                html.Div([html.Small("CPU"), html.Small(f"%{d['cpu']} | {d['temp']}°C")], className="d-flex justify-content-between mb-1"),
                dbc.Progress(value=d['cpu'], color=get_color(d['cpu']), style={"height":"4px"}),
                html.Div([html.Small("RAM"), html.Small(d['mem_v'])], className="d-flex justify-content-between mt-2 mb-1"),
                dbc.Progress(value=d['mem_p'], color=get_color(d['mem_p']), style={"height":"4px"}),
                html.Div([html.Small("SWAP"), html.Small(d['swp_v'])], className="d-flex justify-content-between mt-2 mb-1"),
                dbc.Progress(value=d['swp_p'], color="secondary", style={"height":"4px"}),
                html.Div([html.Small("DISK"), html.Small(d['disk_v'])], className="d-flex justify-content-between mt-2 mb-1"),
                dbc.Progress(value=d['disk_p'], color=get_color(d['disk_p']), style={"height":"4px"}),
                html.Div(d['net_instant'], style={"textAlign":"center","fontSize":"12px","marginTop":"10px","fontWeight":"bold"}),
                html.Div(d['net_total'], style={"textAlign":"center","fontSize":"10px","color":"#888"}),
                html.Div(d['upt'], style={"fontSize":"9px","color":"#555","textAlign":"center","marginTop":"5px"})
            ]))
            os_labels.append(d['os'])
            
    return contents, os_labels

@app.callback(
    [Output("tabs-nav", "active_tab", allow_duplicate=True), Output("edit-id-store", "data", allow_duplicate=True),
     Output("add-name", "value"), Output("add-ip", "value"), Output("add-user", "value"), Output("add-key", "value")],
    [Input("save-btn", "n_clicks"), Input({"type":"del-btn","index":ALL}, "n_clicks"), Input({"type":"edit-btn","index":ALL}, "n_clicks")],
    [State("add-name", "value"), State("add-ip", "value"), State("add-user", "value"), State("add-key", "value"), State("edit-id-store", "data")],
    prevent_initial_call=True
)
def handle_config(n_s, n_d, n_e, name, ip, user, key, eid):
    ctx = callback_context
    tr = ctx.triggered[0]['prop_id']
    servers = load_servers()

    if "edit-btn" in tr:
        sid = json.loads(tr.split('.')[0])['index']
        s = next(x for x in servers if str(x['id']) == str(sid))
        return no_update, sid, s['name'], s['ip'], s['user'], s.get('ssh_key','')
    
    if "save-btn" in tr:
        if not name or not ip: return no_update
        new_s = {"id": eid or str(int(time.time())), "name": name, "ip": ip, "user": user, "ssh_key": key, "alerts": next((x['alerts'] for x in servers if str(x['id'])==str(eid)), {"cpu":90,"temp":75,"ram":85,"disk":90,"offline_sec":30})}
        servers = [new_s if str(x['id'])==str(eid) else x for x in servers] if eid else servers + [new_s]
        save_servers(servers)
        return "tab-dash", None, "", "", "", ""
    
    if "del-btn" in tr:
        sid = json.loads(tr.split('.')[0])['index']
        save_servers([x for x in servers if str(x['id']) != str(sid)])
        return "tab-mgmt", None, "", "", "", ""
    return [no_update]*6

@app.callback(
    Output("tabs-nav", "active_tab", allow_duplicate=True),
    Input({"type":"btn-al-save","index":ALL}, "n_clicks"),
    [State({"type":"in-off","index":ALL}, "value"), State({"type":"in-cpu","index":ALL}, "value"), State({"type":"in-ram","index":ALL}, "value"), State({"type":"in-disk","index":ALL}, "value")],
    prevent_initial_call=True
)
def handle_alerts(n, off, cpu, ram, disk):
    if not any(n): return no_update
    sid = json.loads(callback_context.triggered[0]['prop_id'].split('.')[0])['index']
    servers = load_servers()
    for i, s in enumerate(servers):
        if str(s['id']) == str(sid):
            s['alerts'] = {"offline_sec": off[i], "cpu": cpu[i], "ram": ram[i], "disk": disk[i]}
            break
    save_servers(servers)
    return "tab-alerts"

if __name__ == '__main__':
    app.run(debug=False, port=8050, host='0.0.0.0')