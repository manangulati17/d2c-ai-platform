import { NavLink } from 'react-router-dom';
import './Footer.css';

function Footer() {
  return (
    <footer className="footer">
      <div className="footer-left">
        <span className="footer-brand">D2C INTEL</span>
        <span className="footer-brand-suffix">· v0.1</span>
      </div>

      <div className="footer-center">
        <NavLink to="/chat" className="footer-link">
          Chat
        </NavLink>
        <NavLink to="/metrics" className="footer-link">
          Metrics
        </NavLink>
      </div>

      <div className="footer-right">
        <a href="tel:9650499548" className="footer-contact">
          9650499548
        </a>
        <span className="footer-separator">·</span>
        <a href="mailto:manangulati17@gmail.com" className="footer-contact">
          manangulati17@gmail.com
        </a>
      </div>
    </footer>
  );
}

export default Footer;
