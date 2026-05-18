import { NavLink } from 'react-router-dom';
import './Navbar.css';

function Navbar({ merchantId, setMerchantId }) {
  return (
    <nav className="navbar">
      <div className="navbar-left">
        <span className="navbar-brand">D2C INTEL</span>
        <span className="navbar-brand-suffix">· AI Platform</span>
      </div>

      <div className="navbar-center">
        <NavLink to="/chat" className={({ isActive }) => isActive ? 'navbar-tab navbar-tab-active' : 'navbar-tab'}>
          CHAT
        </NavLink>
        <NavLink to="/metrics" className={({ isActive }) => isActive ? 'navbar-tab navbar-tab-active' : 'navbar-tab'}>
          METRICS
        </NavLink>
      </div>

      <div className="navbar-right">
        <label htmlFor="merchant-id-input" className="navbar-merchant-label">
          MERCHANT ID
        </label>
        <input
          id="merchant-id-input"
          type="text"
          className="navbar-merchant-input"
          value={merchantId}
          onChange={(e) => setMerchantId(e.target.value)}
          placeholder="Enter merchant UUID..."
        />
      </div>
    </nav>
  );
}

export default Navbar;
