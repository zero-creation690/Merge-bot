# 🚀 Ultra Fast Subtitle Merge Bot

A high-performance Telegram bot that merges subtitles with videos at ultra-fast speeds (up to 10+ MB/s).

## ✨ Features

- ⚡ **Lightning Fast Downloads**: Up to 10+ MB/s with multi-threaded processing
- 📦 **Large File Support**: Handles videos up to 4GB
- 🔥 **Permanent Subtitle Burning**: Hardcodes subtitles into video
- 📊 **Real-time Progress**: Live speed tracking and ETA
- 🎯 **Smart Processing**: Uses FFmpeg with ultrafast preset
- 🔄 **100 Workers**: Multi-threaded concurrent operations

## 🛠️ Tech Stack

- **Python 3.11**
- **Pyrogram** - Fast Telegram MTProto API framework
- **FFmpeg** - Video processing
- **Docker** - Containerization
- **Koyeb** - Cloud hosting

---

## 🚀 Deploy on Koyeb (Recommended)

### Method 1: One-Click Deploy (Easiest)

[![Deploy to Koyeb](https://www.koyeb.com/static/images/deploy/button.svg)](https://app.koyeb.com/deploy)

1. Click the button above
2. Connect your GitHub repository
3. Set environment variables (see below)
4. Click "Deploy"

### Method 2: Manual Deploy

#### Prerequisites
- Koyeb account (free tier available)
- Telegram Bot Token
- Telegram API credentials

#### Step 1: Get Telegram Credentials

1. **Bot Token**: 
   - Go to [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow instructions
   - Copy the bot token

2. **API Credentials**:
   - Go to [my.telegram.org](https://my.telegram.org)
   - Login with your phone number
   - Go to "API Development Tools"
   - Create an application
   - Copy `API_ID` and `API_HASH`

#### Step 2: Prepare GitHub Repository

1. **Fork or Clone this repository**
   ```bash
   git clone https://github.com/yourusername/ultra-fast-subtitle-bot.git
   cd ultra-fast-subtitle-bot
   ```

2. **Repository Structure**:
   ```
   ultra-fast-subtitle-bot/
   ├── main.py              # Main bot code
   ├── requirements.txt     # Python dependencies
   ├── Dockerfile          # Docker configuration
   ├── README.md           # This file
   └── .gitignore          # Git ignore file
   ```

#### Step 3: Deploy on Koyeb

1. **Login to Koyeb**
   - Go to [app.koyeb.com](https://app.koyeb.com)
   - Sign up or login

2. **Create New App**
   - Click "Create App"
   - Choose "GitHub" as source
   - Connect your GitHub account
   - Select your repository

3. **Configure Build Settings**
   - **Builder**: Docker
   - **Dockerfile**: ./Dockerfile
   - **Build command**: (leave empty)
   - **Run command**: (leave empty, defined in Dockerfile)

4. **Set Environment Variables**
   Add these in the "Environment Variables" section:
   
   | Variable | Value | Description |
   |----------|-------|-------------|
   | `API_ID` | Your API ID | From my.telegram.org |
   | `API_HASH` | Your API Hash | From my.telegram.org |
   | `BOT_TOKEN` | Your Bot Token | From @BotFather |

5. **Instance Settings**
   - **Region**: Choose closest to your users
   - **Instance Type**: 
     - Free tier: nano (512MB RAM)
     - Recommended: small (1GB RAM) or medium (2GB RAM)
   - **Scaling**: 1 instance (or more for high traffic)

6. **Deploy**
   - Click "Deploy"
   - Wait 3-5 minutes for build and deployment
   - Check logs for "✅ Bot is now ONLINE!"

---

## 🔧 Local Development

### Requirements
- Python 3.11+
- FFmpeg installed
- Telegram API credentials

### Setup

1. **Clone repository**
   ```bash
   git clone https://github.com/yourusername/ultra-fast-subtitle-bot.git
   cd ultra-fast-subtitle-bot
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate  # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install FFmpeg**
   - **Ubuntu/Debian**: `sudo apt install ffmpeg`
   - **macOS**: `brew install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

5. **Set environment variables**
   ```bash
   export API_ID=your_api_id
   export API_HASH=your_api_hash
   export BOT_TOKEN=your_bot_token
   ```

6. **Run bot**
   ```bash
   python main.py
   ```

---

## 📖 Usage

1. **Start the bot**: Send `/start` to your bot
2. **Send video**: Upload your video file (up to 4GB)
3. **Send subtitle**: Upload your .srt subtitle file
4. **Wait**: Bot will process and send merged video
5. **Done**: Download your video with burned-in subtitles!

### Commands

- `/start` - Start the bot and show welcome message
- `/help` - Display help and information
- `/cancel` - Cancel current operation
- `/stats` - View bot statistics

---

## 🎯 Performance Optimization

### Koyeb Instance Recommendations

| Users | Instance Type | RAM | vCPU | Monthly Cost |
|-------|--------------|-----|------|--------------|
| 1-10 | nano | 512MB | 0.1 | Free |
| 10-50 | small | 1GB | 0.5 | $5.50 |
| 50-200 | medium | 2GB | 1 | $14.40 |
| 200+ | large | 4GB | 2 | $28.80 |

### Speed Optimization Tips

1. **Choose closest region** to your users
2. **Use medium or large instance** for 4GB videos
3. **Monitor CPU usage** in Koyeb dashboard
4. **Scale horizontally** if needed (multiple instances)

---

## 🐛 Troubleshooting

### Bot not starting
- Check environment variables are set correctly
- Verify bot token is valid
- Check Koyeb logs for errors

### Slow download speeds
- Upgrade Koyeb instance size
- Check your internet connection
- Telegram has built-in limits (not bot-related)

### FFmpeg errors
- Ensure Dockerfile includes FFmpeg installation
- Check video format is supported
- Verify subtitle file is valid .srt

### Out of memory
- Upgrade to larger instance
- Reduce concurrent operations
- Process smaller files

---

## 📊 Monitoring

### Koyeb Dashboard
- View real-time logs
- Monitor CPU and RAM usage
- Check request metrics
- View uptime statistics

### Bot Statistics
- Send `/stats` to bot for current status
- Shows active users
- Displays performance metrics

---

## 🔒 Security

- Never commit API credentials to Git
- Use environment variables for sensitive data
- Keep dependencies updated
- Monitor bot for abuse

---

## 📝 File Formats

### Supported Video Formats
- MP4, MKV, AVI, MOV, FLV, WMV, WEBM, MPG, MPEG

### Supported Subtitle Format
- SRT (SubRip) only

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

---

## 📄 License

This project is open source and available under the MIT License.

---

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/ultra-fast-subtitle-bot/issues)
- **Telegram**: [@YourSupportBot](https://t.me/YourSupportBot)
- **Email**: support@yourdomain.com

---

## 🎉 Credits

- Built with [Pyrogram](https://docs.pyrogram.org/)
- Video processing by [FFmpeg](https://ffmpeg.org/)
- Hosted on [Koyeb](https://www.koyeb.com/)

---

## 🔮 Roadmap

- [ ] Support for more subtitle formats (ASS, VTT)
- [ ] Custom subtitle styling options
- [ ] Batch processing support
- [ ] Web interface for management
- [ ] Multi-language subtitle support
- [ ] Video quality selection

---

**Made with ❤️ for ultra-fast video processing**
