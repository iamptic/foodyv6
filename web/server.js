// Foody web server (Express)
const express = require('express');
const path = require('path');
const app = express();

const FOODY_API = process.env.FOODY_API || '';

// Disable etag + force no-cache for HTML and /config.js
app.disable('etag');
app.use((req,res,next)=>{
  if (req.path.endsWith('.html') || req.path === '/' || req.path === '/config.js') {
    res.set('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
    res.set('Pragma', 'no-cache');
    res.set('Expires', '0');
    res.set('Surrogate-Control', 'no-store');
  }
  next();
});

app.get('/config.js', (req,res)=>{
  if (!FOODY_API || !/^https?:\/\//.test(FOODY_API)) {
    res.type('application/javascript').send(`console.error('FOODY_API is not set or invalid'); window.FOODY_API='';`);
  } else {
    res.type('application/javascript').send(`window.FOODY_API=${JSON.stringify(FOODY_API)};`);
  }
});

// Static site
app.use('/web', express.static(path.join(__dirname, 'web'), { maxAge: 0 }));

// Default route
app.get('/', (req,res)=> res.redirect('/web/buyer/'));

const PORT = process.env.PORT || 8080;
app.listen(PORT, ()=> console.log('Foody web running on', PORT, 'FOODY_API=', FOODY_API));