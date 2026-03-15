# THIS ENTIRE PROJECT WAS BUILT WITH AI BASED OFF nvalis/HeadlessScan
# THANK YOU @nvalis FOR THE ORIGINAL PROJECT
# DON'T EXPOSE THIS TO THE INTERNET

I just needed something quick with a couple extra features to control my ES-50.

There are bugs.
# HeadlessScan

A modern, headless document scanning interface for Epson ADF (Automatic Document Feeder) scanners. Built with FastAPI backend and React frontend, designed specifically for paperless-ng integration.

![HeadlessScan Interface](https://img.shields.io/badge/Status-Active-green) ![Python](https://img.shields.io/badge/Python-3.8+-blue) ![React](https://img.shields.io/badge/React-18+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green)

## Features

- 🖨️ **Epson Scanner Support**: Native integration with Epson Scan 2 for ADF scanners
- 📄 **Multiple Formats**: Output to PDF, PNG, or JPG formats
- 🔄 **Auto-Scan Mode**: Continuous scanning with configurable timeouts
- 🌐 **Web Interface**: Modern React-based UI with real-time updates via WebSocket
- 🔗 **Webhook Support**: POST scan completion notifications to external services
- 📁 **Flexible Storage**: Save scans to custom directories or integrate with paperless-ng
- ⚙️ **Systemd Service**: Easy installation as a system service
- 📊 **Batch Management**: Organize and manage scan batches with preview and download

## Requirements

### Hardware
- Epson scanner with ADF (Automatic Document Feeder)
- Epson Scan 2 software installed

### Software
- **Python 3.8+**
- **Node.js 16+** and **npm**
- **ImageMagick** (for PDF conversion)
- Linux (tested on Debian/Ubuntu)

## Quick Start

### Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/nvalis/HeadlessScan.git
   cd HeadlessScan
   ```

2. **Start the application**
   ```bash
   ./start.sh
   ```

3. **Open your browser**
   - Frontend: http://localhost:5173
   - API Docs: http://localhost:8000/docs

### Production Installation

For production use, install as a systemd service:

```bash
sudo ./install-service.sh
sudo systemctl start headlessscan
```

## Configuration

### Default Settings (config.json)

```json
{
  "_comment": "HeadlessScan default settings. All values here pre-fill the UI on startup.",
  "format": "pdf",
  "timeout": 10,
  "dpi": 300,
  "duplex": false,
  "blank_page_skip": false,
  "output_dir": "",
  "webhook_url": "",
  "autostart_autoscan": false
}
```

### Scanner Settings (settings.json)

This file contains the Epson Scan 2 configuration. It's automatically generated based on your scanner model and should not be edited manually.

## Usage

### Web Interface

1. **Manual Scanning**:
   - Select output format (PDF/PNG/JPG)
   - Configure DPI, duplex, and other options
   - Set output directory (optional)
   - Configure webhook URL (optional)
   - Click "Start Scan"

2. **Auto-Scan Mode**:
   - Configure scan settings
   - Click "Enable Auto-scan"
   - Scanner will continuously scan documents as they're inserted

3. **Batch Management**:
   - View all scan batches in the table
   - Preview scans before downloading
   - Rename batches and files
   - Download individual files or entire batches

### Command Line

For basic scanning without the web interface:

```bash
python3 scan.py settings.json --output my_scan.pdf --dpi 300 --duplex
```

## API Reference

### REST Endpoints

- `GET /api/status` - Get current scanner status
- `GET /api/config` - Get default configuration
- `GET /api/batches` - List all scan batches
- `POST /api/scan/start` - Start a manual scan
- `POST /api/scan/stop` - Stop current scan
- `POST /api/autoscan/enable` - Enable auto-scan mode
- `POST /api/autoscan/disable` - Disable auto-scan mode
- `PUT /api/batches/{id}` - Rename a batch
- `DELETE /api/batches/{id}` - Delete a batch

### WebSocket

- `ws://localhost:8000/ws/logs` - Real-time log streaming

### Webhook Payload

When a webhook URL is configured, HeadlessScan will POST JSON data on scan completion:

```json
{
  "event": "scan_complete",
  "batch_id": "uuid-string",
  "success": true,
  "pages": 5,
  "files": ["/path/to/scan.pdf"]
}
```

## Integration with Paperless-ng

HeadlessScan is designed to work seamlessly with paperless-ng:

1. Set the output directory to your paperless-ng consume folder:
   ```
   /opt/paperless-ng/consume
   ```

2. Configure webhooks to trigger paperless-ng processing (if needed)

3. Use auto-scan mode for continuous document ingestion

## Troubleshooting

### Common Issues

**Scanner not found**
- Ensure Epson Scan 2 is installed and configured
- Check scanner USB connection
- Verify scanner is powered on

**PDF conversion fails**
- Install ImageMagick: `sudo apt install imagemagick`
- Check ImageMagick policy for PDF writing in `/etc/ImageMagick-6/policy.xml`

**Permission errors**
- Ensure the service user has access to output directories
- Check scanner device permissions

**Frontend not loading**
- Verify Node.js and npm are installed
- Check that ports 5173 and 8000 are available

### Logs

View application logs:
```bash
# Development
./start.sh  # Logs appear in terminal

# Production
sudo journalctl -u headlessscan -f
```

## Development

### Project Structure

```
HeadlessScan/
├── backend/           # FastAPI backend
│   ├── main.py       # Main application
│   ├── scanner.py    # Scanner logic
│   └── requirements.txt
├── frontend/         # React frontend
│   ├── src/
│   ├── package.json
│   └── vite.config.js
├── config.json       # Default UI settings
├── settings.json     # Epson Scan 2 config
├── scan.py          # CLI scanner
├── start.sh         # Development startup
└── install-service.sh # Production installer
```

### Building Frontend

```bash
cd frontend
npm install
npm run build
```

The built frontend is served by the FastAPI backend from `frontend/dist/`.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

### Development Setup

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd frontend
npm install
npm run dev
```

## License

This project is open source and available under the MIT License.

## Acknowledgments

- Built for the paperless-ng community
- Uses Epson Scan 2 for scanner integration
- ImageMagick for PDF processing
- FastAPI and React for the web interface