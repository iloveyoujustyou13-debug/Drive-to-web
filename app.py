import os
import mimetypes
from flask import Flask, redirect, url_for, session, request, jsonify, abort, render_template_string
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# লোকাল কম্পিউটারে বা মোবাইলে HTTP-তে রান করার জন্য সিকিউরিটি শিথিল করা হলো
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)
app.secret_key = 'super_secret_session_key_change_this_in_production'

# গুগল ড্রাইভ রিড-অনলি স্কোপ
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
CLIENT_SECRETS_FILE = "credentials.json"

# সাময়িকভাবে ওয়েবসাইট লিংক মনে রাখার ডিকশনারি (site_name -> folder_id)
DEPLOYED_SITES = {}

# আলাদা HTML ফাইল না রেখে সরাসরি পাইথনের ভেতরেই সম্পূর্ণ HTML ও Tailwind CSS কোড রাখা হলো
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Drive to Web Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 text-gray-800">

    <nav class="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center">
        <h1 class="text-xl font-bold text-indigo-600 flex items-center gap-2">
            🌐 DriveToWeb <span class="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">Single File Engine</span>
        </h1>
        <div>
            {% if is_connected %}
                <a href="/auth/logout" class="text-sm font-medium text-red-500 hover:text-red-700 transition">Disconnect Drive</a>
            {% endif %}
        </div>
    </nav>

    <div class="max-w-6xl mx-auto mt-10 px-4">
        {% if not is_connected %}
        <div class="text-center bg-white border border-gray-200 rounded-2xl p-16 shadow-sm max-w-2xl mx-auto">
            <div class="text-5xl mb-4">🚀</div>
            <h2 class="text-2xl font-bold text-gray-900 mb-2">Turn Google Drive Folders into Live Websites</h2>
            <p class="text-gray-500 mb-8">Connect your Google Drive account, select a folder containing HTML, CSS, or JS, and publish it instantly.</p>
            <a href="/auth/login" class="inline-flex items-center justify-center px-6 py-3 bg-indigo-600 text-white font-medium rounded-xl shadow-lg hover:bg-indigo-700 transition">
                Connect Google Drive Account
            </a>
        </div>
        {% else %}
        <div class="grid grid-cols-1 md:grid-cols-3 gap-8">
            
            <div class="md:col-span-2 bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="font-bold text-gray-900 text-lg">Select Storage Directory</h3>
                    <button onclick="loadFolder('root')" class="text-xs font-semibold text-indigo-600 hover:underline">🔄 Reset to Root</button>
                </div>
                
                <div id="file-list" class="divide-y divide-gray-100 max-h-[400px] overflow-y-auto border border-gray-100 rounded-lg">
                    <p class="p-4 text-sm text-gray-400 text-center">Loading files from Google Drive...</p>
                </div>
            </div>

            <div class="bg-white border border-gray-200 rounded-xl p-6 shadow-sm flex flex-col justify-between">
                <div>
                    <h3 class="font-bold text-gray-900 text-lg mb-4">Deploy Folder</h3>
                    
                    <div class="mb-4">
                        <label class="block text-xs font-bold uppercase text-gray-500 mb-1">Selected Folder ID</label>
                        <input id="selected-folder-id" type="text" readonly class="w-full bg-gray-50 text-gray-400 text-sm border border-gray-200 rounded-lg p-2.5 outline-none" placeholder="No folder selected">
                    </div>

                    <div class="mb-6">
                        <label class="block text-xs font-bold uppercase text-gray-500 mb-1">Website Name (Slug)</label>
                        <input id="site-slug-input" type="text" class="w-full text-sm border border-gray-200 rounded-lg p-2.5 outline-none focus:border-indigo-500" placeholder="my-portfolio">
                    </div>
                </div>

                <button onclick="triggerDeploymentPipeline()" class="w-full py-3 bg-emerald-600 text-white font-medium rounded-xl hover:bg-emerald-700 transition shadow-md">
                    🚀 Deploy Production Site
                </button>
            </div>
        </div>

        <div class="mt-12 bg-white border border-gray-200 rounded-xl p-6 shadow-sm mb-12">
            <h3 class="font-bold text-gray-900 text-lg mb-4">Live Deployed Environments</h3>
            <div id="deployed-sites-list" class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <p class="text-sm text-gray-400 col-span-2">No websites deployed yet.</p>
            </div>
        </div>
        {% endif %}
    </div>

    <script>
        let selectedFolderId = '';

        async function loadFolder(folderId) {
            const container = document.getElementById('file-list');
            container.innerHTML = '<p class="p-4 text-sm text-gray-400 text-center">Fetching contents...</p>';
            
            try {
                const response = await fetch(`/api/drive/list/${folderId}`);
                const data = await response.json();
                
                if (data.error || !data.files || data.files.length === 0) {
                    container.innerHTML = '<p class="p-4 text-sm text-gray-400 text-center">No files or folders found here.</p>';
                    return;
                }

                container.innerHTML = '';
                data.files.forEach(item => {
                    const isFolder = item.mimeType === 'application/vnd.google-apps.folder';
                    const div = document.createElement('div');
                    div.className = "p-3 flex justify-between items-center hover:bg-gray-50 transition cursor-pointer";
                    
                    div.innerHTML = `
                        <div class="flex items-center gap-3">
                            <span class="text-xl">${isFolder ? '📁' : '📄'}</span>
                            <div>
                                <p class="text-sm font-medium text-gray-800">${item.name}</p>
                            </div>
                        </div>
                    `;
                    
                    if (isFolder) {
                        div.onclick = () => {
                            selectedFolderId = item.id;
                            document.getElementById('selected-folder-id').value = item.id;
                            loadFolder(item.id);
                        };
                    }
                    container.appendChild(div);
                });
            } catch (err) {
                container.innerHTML = '<p class="p-4 text-sm text-red-500 text-center">Error reading data from server.</p>';
            }
        }

        async function triggerDeploymentPipeline() {
            const name = document.getElementById('site-slug-input').value;
            if (!selectedFolderId || !name) {
                alert('Please select a folder and enter a website name.');
                return;
            }

            const res = await fetch('/api/deploy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ folderId: selectedFolderId, siteName: name })
            });
            const result = await res.json();

            if (result.success) {
                const list = document.getElementById('deployed-sites-list');
                if(list.querySelector('p')) list.innerHTML = '';
                
                const siteCard = document.createElement('div');
                siteCard.className = "p-4 border border-gray-100 rounded-xl bg-gray-50 flex justify-between items-center shadow-sm";
                siteCard.innerHTML = `
                    <div>
                        <h4 class="font-bold text-sm text-gray-900">${name}.localweb</h4>
                        <p class="text-xs text-gray-400">Folder ID: ${selectedFolderId}</p>
                    </div>
                    <a href="${result.siteUrl}" target="_blank" class="px-3 py-1.5 bg-white text-indigo-600 font-medium text-xs border border-gray-200 rounded-lg hover:border-indigo-500 transition">Visit Site ↗</a>
                `;
                list.appendChild(siteCard);
                alert('Website successfully deployed locally!');
            } else {
                alert('Error processing production stack configurations.');
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            if (document.getElementById('file-list')) {
                loadFolder('root');
            }
        });
    </script>
</body>
</html>
"""

def get_drive_service():
    if 'credentials' not in session:
        return None
    from google.oauth2.credentials import Credentials
    creds = Credentials(**session['credentials'])
    return build('drive', 'v3', credentials=creds)

@app.route('/')
def index():
    is_connected = 'credentials' in session
    # render_template_string ব্যবহার করে পাইথন ভ্যারিয়েবল থেকেই HTML রেন্ডার করা হচ্ছে
    return render_template_string(DASHBOARD_TEMPLATE, is_connected=is_connected)

@app.route('/auth/login')
def login():
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES,
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    authorization_url, state = flow.authorization_url(access_type='offline', include_granted_scopes='true')
    session['state'] = state
    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = session['state']
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state,
        redirect_uri=url_for('oauth2callback', _external=True)
    )
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    return redirect(url_for('index'))

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/drive/list/<folder_id>')
def list_folder_contents(folder_id):
    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        return jsonify({'files': results.get('files', [])})
    except HttpError as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/deploy', methods=['POST'])
def deploy_site():
    data = request.json
    folder_id = data.get('folderId')
    site_name = data.get('siteName', '').strip().lower().replace(' ', '-')
    
    if not folder_id or not site_name:
        return jsonify({'error': 'Invalid site configuration'}), 400
        
    DEPLOYED_SITES[site_name] = folder_id
    return jsonify({'success': True, 'siteUrl': f'/site/{site_name}/index.html'})

@app.route('/site/<site_name>/<path:filename>')
def serve_deployed_site(site_name, filename):
    folder_id = DEPLOYED_SITES.get(site_name)
    if not folder_id:
        return abort(404, description="Site not found")
        
    service = get_drive_service()
    if not service:
        return "Session expired. Please log in again.", 401

    try:
        query = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)").execute()
        files = results.get('files', [])
        
        if not files:
            return abort(404, description="File not found")
            
        file_metadata = files[0]
        file_id = file_metadata['id']
        mime_type = file_metadata['mimeType']
        
        request_media = service.files().get_media(fileId=file_id)
        content = request_media.execute()
        
        if mime_type == 'application/octet-stream' or mime_type == 'text/plain':
            guessed_type, _ = mimetypes.guess_type(filename)
            mime_type = guessed_type or mime_type
            
        return content, 200, {'Content-Type': mime_type}
        
    except HttpError as error:
        return f"Error: {error}", 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
