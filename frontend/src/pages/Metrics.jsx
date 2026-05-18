import { useState, useEffect } from 'react';
import './Metrics.css';

function Metrics({ merchantId }) {
  const [connectors, setConnectors] = useState([]);
  const [loadingConnectors, setLoadingConnectors] = useState(false);
  const [logs, setLogs] = useState([]);
  const [loadingLogs, setLoadingLogs] = useState(false);
  const [logsError, setLogsError] = useState('');
  const [expandedLogId, setExpandedLogId] = useState(null);
  const [expandedLogData, setExpandedLogData] = useState({});
  const [runningAgent, setRunningAgent] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [registeringDemo, setRegisteringDemo] = useState(false);
  const [demoMessage, setDemoMessage] = useState('');

  useEffect(() => {
    if (merchantId) {
      fetchConnectors();
      fetchLogs();
      const interval = setInterval(fetchLogs, 30000);
      return () => clearInterval(interval);
    }
  }, [merchantId]);

  const fetchConnectors = async () => {
    setLoadingConnectors(true);
    try {
      const response = await fetch(`http://localhost:8000/merchants/${merchantId}/connectors`);
      if (!response.ok) throw new Error('Failed to fetch connectors');
      const data = await response.json();
      setConnectors(data);
    } catch (err) {
      console.error('Error fetching connectors:', err);
    } finally {
      setLoadingConnectors(false);
    }
  };

  const fetchLogs = async () => {
    if (!merchantId) return;
    
    setLoadingLogs(true);
    setLogsError('');
    try {
      const response = await fetch(`http://localhost:8000/merchants/${merchantId}/agent/logs`);
      if (!response.ok) throw new Error('Failed to fetch logs');
      const data = await response.json();
      setLogs(data);
    } catch (err) {
      console.error('Error fetching logs:', err);
      setLogsError('Failed to load agent logs');
    } finally {
      setLoadingLogs(false);
    }
  };

  const toggleLogExpansion = async (logId) => {
    if (expandedLogId === logId) {
      setExpandedLogId(null);
      return;
    }

    setExpandedLogId(logId);

    if (!expandedLogData[logId]) {
      try {
        const response = await fetch(`http://localhost:8000/merchants/${merchantId}/agent/logs/${logId}`);
        if (!response.ok) throw new Error('Failed to fetch log details');
        const data = await response.json();
        setExpandedLogData(prev => ({ ...prev, [logId]: data }));
      } catch (err) {
        console.error('Error fetching log details:', err);
      }
    }
  };

  const handleRunAgent = async () => {
    setRunningAgent(true);
    setTaskId('');
    try {
      // Use sync=true for testing (no Celery required)
      const response = await fetch(`http://localhost:8000/merchants/${merchantId}/agent/run?sync=true`, {
        method: 'POST'
      });
      if (!response.ok) throw new Error('Failed to trigger agent run');
      const data = await response.json();
      setTaskId(data.task_id);
      setTimeout(() => {
        fetchLogs();
        setTaskId('');
      }, 1000);
    } catch (err) {
      console.error('Agent run error:', err);
      setTaskId('Error: ' + (err.message || 'Failed to run agent'));
    } finally {
      setRunningAgent(false);
    }
  };

  const handleRegisterDemoConnectors = async () => {
    setRegisteringDemo(true);
    setDemoMessage('');
    try {
      const response = await fetch(
        `http://localhost:8000/merchants/${merchantId}/connectors/demo/register`,
        { method: 'POST' }
      );
      if (!response.ok) throw new Error('Failed to register demo connectors');
      const data = await response.json();
      setDemoMessage(data.message);
      fetchConnectors();
      setTimeout(() => setDemoMessage(''), 5000);
    } catch (err) {
      console.error('Demo connector error:', err);
      setDemoMessage('Error: ' + (err.message || 'Failed to register connectors'));
    } finally {
      setRegisteringDemo(false);
    }
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const day = date.getDate().toString().padStart(2, '0');
    const month = months[date.getMonth()];
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');
    return `${day} ${month}, ${hours}:${minutes}`;
  };

  const getModeBadgeClass = (mode) => {
    if (!mode) return 'metrics-mode-badge-none';
    if (mode === 'healthy') return 'metrics-mode-badge-healthy';
    if (mode === 'spend_without_conversion') return 'metrics-mode-badge-error';
    if (mode === 'orders_without_settlement') return 'metrics-mode-badge-warning';
    if (mode === 'conversion_with_returns') return 'metrics-mode-badge-orange';
    return 'metrics-mode-badge-none';
  };

  const formatConfidence = (score) => {
    if (score == null) return '—';
    return `${Math.round(parseFloat(score) * 100)}%`;
  };

  if (!merchantId) {
    return (
      <div className="metrics-page">
        <div className="metrics-empty-merchant">
          Enter a Merchant ID above to get started.
        </div>
      </div>
    );
  }

  return (
    <div className="metrics-page">
      <div className="metrics-body">
        <div className="metrics-left-panel">
          <div className="metrics-section">
            <div className="metrics-section-label">CONNECTORS</div>
            {loadingConnectors ? (
              <div className="metrics-loading">Loading...</div>
            ) : connectors.length === 0 ? (
              <div>
                <div className="metrics-empty">No connectors registered.</div>
                <button
                  className="metrics-demo-btn"
                  onClick={handleRegisterDemoConnectors}
                  disabled={registeringDemo}
                  style={{ marginTop: '12px' }}
                >
                  {registeringDemo ? 'REGISTERING...' : 'Register Demo Connectors'}
                </button>
                {demoMessage && <div className="metrics-demo-message" style={{ marginTop: '8px', fontSize: '12px', color: '#00d4ff' }}>{demoMessage}</div>}
              </div>
            ) : (
              connectors.map((conn) => (
                <div key={conn.id} className="metrics-connector-card">
                  <span className="metrics-connector-name">{conn.connector_type.toUpperCase()}</span>
                  <div className={`metrics-connector-dot ${conn.is_active ? 'metrics-connector-active' : 'metrics-connector-inactive'}`}></div>
                </div>
              ))
            )}
          </div>

        </div>

        <div className="metrics-right-panel">
          <div className="metrics-logs-header">
            <div className="metrics-section-label">AGENT LOGS</div>
            <button
              className="metrics-run-btn"
              onClick={handleRunAgent}
              disabled={runningAgent}
            >
              {runningAgent ? 'RUNNING...' : 'RUN AGENT →'}
            </button>
          </div>
          {taskId && <div className="metrics-task-id">task: {taskId}</div>}

          {loadingLogs ? (
            <div className="metrics-loading-center">Loading logs...</div>
          ) : logsError ? (
            <div className="metrics-error-center">{logsError}</div>
          ) : logs.length === 0 ? (
            <div className="metrics-empty-center">No agent runs yet.</div>
          ) : (
            <div className="metrics-logs-table">
              <div className="metrics-logs-header-row">
                <div style={{ flex: 2 }}>RUN AT</div>
                <div style={{ flex: 2 }}>MODE</div>
                <div style={{ flex: 1 }}>STATUS</div>
                <div style={{ flex: 1 }}>CONFIDENCE</div>
              </div>

              {logs.map((log) => {
                const isExpanded = expandedLogId === log.id;
                const detailData = expandedLogData[log.id];

                return (
                  <div key={log.id} className="metrics-log-row">
                    <div
                      className="metrics-log-row-main"
                      onClick={() => toggleLogExpansion(log.id)}
                    >
                      <div style={{ flex: 2 }} className="metrics-log-date">
                        {formatDate(log.run_at)}
                      </div>
                      <div style={{ flex: 2 }}>
                        <span className={`metrics-mode-badge ${getModeBadgeClass(log.detection_mode)}`}>
                          {log.detection_mode ? log.detection_mode.replace(/_/g, ' ') : '—'}
                        </span>
                      </div>
                      <div style={{ flex: 1 }} className="metrics-log-status">
                        {log.status}
                      </div>
                      <div style={{ flex: 1 }} className="metrics-log-confidence">
                        {formatConfidence(log.confidence_score)}
                      </div>
                    </div>

                    {isExpanded && detailData && (
                      <div className="metrics-log-expanded">
                        <div className="metrics-log-section">
                          <div className="metrics-log-section-label">REASONING</div>
                          <div className="metrics-log-section-text">
                            {detailData.reasoning || '—'}
                          </div>
                        </div>
                        <div className="metrics-log-section">
                          <div className="metrics-log-section-label">RECOMMENDATION</div>
                          <div className="metrics-log-section-text">
                            {detailData.recommendation || '—'}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default Metrics;
