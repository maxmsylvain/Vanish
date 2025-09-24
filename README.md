# Vanish - A Social Platform

Vanish is a social platform where posts disappear after 3 hours. It's designed for authentic, in-the-moment sharing.

## Technologies Used

- **Backend**: Python with Flask
- **Database**: SQLAlchemy (SQLite by default)
- **Frontend**: HTML, CSS, JavaScript
- **Task Scheduling**: APScheduler for automatic post deletion

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/vanish.git
   cd vanish
   ```

2. **Create a virtual environment and activate it:**
   ```bash
   # Windows
   Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
   python -m venv venv
   venv\Scripts\activate
   
   # macOS/Linux
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables (optional):**
   ```bash
   export SECRET_KEY="your-secret-key"
   export DATABASE_URL="your-database-url"  # Default is SQLite
   ```

5. **Run the application:**
   ```bash
   python app.py
   ```

6. **Open your browser and navigate to:**
   ```
   http://localhost:5000
   ```

## Features

- Posts automatically disappear after 3 hours
- Real-time, authentic social sharing
- Lightweight and fast

## Contributing

Feel free to submit issues and enhancement requests!
