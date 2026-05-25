"""k6 load testing script for WebSocket and message throughput."""
import http from 'k6/http';
import { check, sleep } from 'k6';
import ws from 'k6/ws';
import { Rate } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const wsConnectRate = new Rate('ws_connections');
const messageDeliveryRate = new Rate('message_delivery');

export const options = {
  stages: [
    { duration: '30s', target: 100 },   // Ramp up to 100 WS connections
    { duration: '1m', target: 500 },    // Ramp up to 500 WS connections
    { duration: '2m', target: 1000 },   // Ramp up to 1000 WS connections (target)
    { duration: '3m', target: 1000 },   // Stay at 1000 for 3 minutes
    { duration: '1m', target: 0 },      // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],   // 95% of requests should be below 500ms
    errors: ['rate<0.05'],              // Error rate should be below 5%
    ws_connections: ['rate>0.95'],      // 95% WS connection success rate
    message_delivery: ['rate>0.99'],    // 99% message delivery rate
    http_req_failed: ['rate<0.05'],     // 5% error threshold
  },
};

// Test configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const WS_URL = __ENV.WS_URL || 'ws://localhost:8000/ws';

// Login and get token
function login() {
  const res = http.post(`${BASE_URL}/api/v1/auth/login`, JSON.stringify({
    email: `test_${__VU}@example.com`,
    password: 'testpassword123',
  }), {
    headers: { 'Content-Type': 'application/json' },
  });
  
  check(res, {
    'login status is 200': (r) => r.status === 200,
  });
  
  if (res.status === 200) {
    const body = res.json();
    return body.access_token;
  }
  return null;
}

// Main load test scenario
export default function () {
  const token = login();
  if (!token) {
    errorRate.add(1);
    return;
  }
  
  // Test WebSocket connection
  const wsResponse = ws.connect(WS_URL, {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  }, function (socket) {
    socket.on('open', () => {
      wsConnectRate.add(1);
      console.log(`VU ${__VU}: WS connected`);
    });
    
    socket.on('message', (data) => {
      // Verify message received
      messageDeliveryRate.add(1);
    });
    
    socket.on('close', () => {
      console.log(`VU ${__VU}: WS disconnected`);
    });
    
    socket.on('error', (error) => {
      console.error(`VU ${__VU}: WS error: ${error}`);
      errorRate.add(1);
    });
    
    // Send messages periodically
    let messageCount = 0;
    const sendInterval = setInterval(() => {
      if (socket.readyState === 1) { // OPEN
        const message = {
          type: 'chat_message',
          conversation_id: 1,
          content: `Load test message #${messageCount++} from VU ${__VU}`,
          timestamp: new Date().toISOString(),
        };
        
        socket.send(JSON.stringify(message));
        
        // Check circuit breaker state
        if (messageCount % 10 === 0) {
          const healthRes = http.get(`${BASE_URL}/health`);
          check(healthRes, {
            'health check passed': (r) => r.status === 200,
          });
        }
      }
    }, 1000); // Send 1 message per second per connection
    
    // Clean up on close
    socket.setTimeout(() => {
      clearInterval(sendInterval);
      socket.close();
    }, 180000); // Run for 3 minutes per VU
  });
  
  check(wsResponse, {
    'ws connection established': (r) => r && r.status === 101,
  });
  
  if (!wsResponse || wsResponse.status !== 101) {
    wsConnectRate.add(0);
    errorRate.add(1);
  }
  
  sleep(1);
}

// Handle setup (create test users if needed)
export function setup() {
  console.log('Setting up load test...');
  
  // Create test users via registration endpoint
  const userCount = 100;
  for (let i = 0; i < userCount; i++) {
    http.post(`${BASE_URL}/api/v1/auth/register`, JSON.stringify({
      email: `test_${i}@example.com`,
      password: 'testpassword123',
      full_name: `Test User ${i}`,
      workspace_name: `Workspace ${i}`,
    }), {
      headers: { 'Content-Type': 'application/json' },
    });
  }
  
  return { userCount };
}

// Handle teardown (cleanup)
export function teardown(data) {
  console.log(`Load test completed. Created ${data.userCount} users.`);
}
