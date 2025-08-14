import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();

const WEB_DIR = path.join(__dirname, 'web');

// Serve static files from WEB_DIR
app.use(express.static(WEB_DIR));

// Example endpoint
app.get('/config.js', (req, res) => {
  res.type('application/javascript');
  res.send('console.log("Config loaded")');
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Web server running on port ${PORT}`);
});
