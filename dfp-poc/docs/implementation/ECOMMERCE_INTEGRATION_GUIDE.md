# E-Commerce Integration Guide: Extending DFP PoC

**Date**: November 23, 2025  
**Base**: `dfp-poc/` (Azure AD style)  
**Target**: E-commerce anomaly detection  
**Pattern**: Copy base → Customize features → Deploy parallel

---

## OVERVIEW

Extend your **existing working DFP implementation** to detect e-commerce threats:

- **Account Takeover (ATO)**: Credential stuffing, session hijacking
- **Bot Automation**: Inventory hoarding, scalping, price scraping
- **Payment Fraud**: Stolen cards, card testing, promo abuse
- **Application DDoS**: API abuse, rate limit evasion
- **Refund Fraud**: Serial returners, wardrobing, chargeback abuse
- **Promo Code Abuse**: Mass creation, sharing, reselling
- **Cart Abandonment Fraud**: Reservation abuse, fake demand
- **Review Manipulation**: Fake reviews, competitor attacks
- **Gift Card Fraud**: Balance checking, carding, reselling

**Key Principle**: Your existing `dfp-poc/` remains unchanged. Create parallel `dfp-ecommerce/` by copying structure and customizing 2 config files.

---

## YOUR EXISTING IMPLEMENTATION

Your `dfp-poc/` uses **NVIDIA Morpheus DFP** with these reusable components:

```text
dfp-poc/
├── pipelines/
│   ├── training_pipeline.py       ← Copy as-is
│   └── inference_pipeline.py      ← Copy as-is
├── modules/                       ← Copy as-is (all preprocessing, training, inference)
├── config/
│   ├── feature_schema.yaml        ← CUSTOMIZE for e-commerce
│   └── base_config.yaml           ← CUSTOMIZE (Kafka topics)
└── services/                      ← SHARED (no changes needed)
    └── start_services.sh
```

**Current Features** (Azure AD):

- `logcount`, `locincrement`, `appincrement` (NVIDIA standard)
- Device, browser, OS, location, app name

**For E-Commerce**: Change to customer events (login, checkout, cart, payment) with `productincrement`, `paymentincrement`

---

## IMPLEMENTATION

### Step 1: Copy Base

```bash
cd /Users/tzabek/Library/CloudStorage/OneDrive-Deloitte\(O365D\)/Documents/DELOITTE/PROJECTS/morpheus-dfp
cp -r dfp-poc dfp-ecommerce
cd dfp-ecommerce
rm -rf data/.cache/* mlruns/* logs/*
```

### Step 2: Customize Feature Schema

Edit `dfp-ecommerce/config/feature_schema.yaml`:

**Raw Schema** (e-commerce events):

```yaml
raw_schema:
  username: { type: "string" } # Customer email
  timestamp: { type: "datetime" }
  action: { type: "string" } # login, view_product, add_to_cart, checkout, payment, refund, review, gift_card_check
  product_category: { type: "string" }
  product_id: { type: "string" }
  payment_method: { type: "string" }
  device_type: { type: "string" }
  browser: { type: "string" }
  country: { type: "string" }
  shipping_address_hash: { type: "string" } # Hash of shipping address
  billing_address_hash: { type: "string" } # Hash of billing address
  promo_code: { type: "string" }
  order_value: { type: "float" }
  is_guest_checkout: { type: "boolean" }
  session_duration: { type: "float" } # Seconds
  page_views: { type: "integer" } # Pages viewed in session
```

**Behavioral Features**:

```yaml
behavioral_features:
  logcount:
    morpheus_class: "IncrementColumn"
    source: ["username", "timestamp"]

  locincrement:
    morpheus_class: "DistinctIncrementColumn"
    source: ["username", "country", "timestamp"]

  productincrement:
    morpheus_class: "DistinctIncrementColumn"
    source: ["username", "product_category", "timestamp"]

  paymentincrement:
    morpheus_class: "DistinctIncrementColumn"
    source: ["username", "payment_method", "timestamp"]

  shippingincrement: # NEW - Detects address changes
    morpheus_class: "DistinctIncrementColumn"
    source: ["username", "shipping_address_hash", "timestamp"]

  promoincrement: # NEW - Detects promo code testing
    morpheus_class: "DistinctIncrementColumn"
    source: ["username", "promo_code", "timestamp"]

  refundcount: # NEW - Tracks refund requests
    morpheus_class: "IncrementColumn"
    source: ["username", "timestamp"]
    filter: "action == 'refund'"

  reviewcount: # NEW - Tracks review submissions
    morpheus_class: "IncrementColumn"
    source: ["username", "timestamp"]
    filter: "action == 'review'"
```

**Model Features**:

```yaml
model_features:
  default:
    # Categorical features
    - "action"
    - "device_type"
    - "browser"
    - "payment_method"
    - "product_category"
    - "country"
    - "is_guest_checkout"
    # Behavioral counters (NVIDIA standard IncrementColumn/DistinctIncrementColumn)
    - "logcount"
    - "locincrement"
    - "productincrement"
    - "paymentincrement"
    - "shippingincrement" # NEW - Address changes
    - "promoincrement" # NEW - Promo code diversity
    - "refundcount" # NEW - Refund requests
    - "reviewcount" # NEW - Review submissions
```

### Step 3: Update Kafka Topics

Edit `dfp-ecommerce/config/base_config.yaml`:

```yaml
kafka:
  topics:
    input: "ecommerce-events" # NEW topic
    output: "ecommerce-detections" # NEW topic
  consumer:
    group_id: "morpheus-dfp-ecommerce"

paths:
  cache: "./dfp-ecommerce/data/.cache/dfp-ecommerce" # Separate cache

mlflow:
  experiment_name: "dfp/ecommerce" # Separate namespace
```

### Step 4: Start Services (Shared)

```bash
cd dfp-poc
./services/start_services.sh  # Starts Kafka + MLflow for BOTH implementations
```

### Step 5: Create Topics

```bash
kafka-topics --create --bootstrap-server localhost:29092 --topic ecommerce-events --partitions 3
kafka-topics --create --bootstrap-server localhost:29092 --topic ecommerce-detections --partitions 3
```

### Step 6: Train Models

```bash
cd dfp-ecommerce
python pipelines/training_pipeline.py --data-path data/input/ecommerce_history.csv
```

**Data Format**:

```csv
email,event_time,event_type,category,payment_type,device,user_agent_browser,geo_country
user1@example.com,2024-11-01T10:00:00Z,login,,,mobile,Chrome,United Kingdom
user1@example.com,2024-11-01T10:05:00Z,view_product,Electronics,,mobile,Chrome,United Kingdom
user1@example.com,2024-11-01T10:10:00Z,checkout,Electronics,card,mobile,Chrome,United Kingdom
```

### Step 7: Run Inference

```bash
cd dfp-ecommerce
python pipelines/inference_pipeline.py  # Streams from ecommerce-events
```

---

## PARALLEL OPERATION

Run both Azure AD and e-commerce simultaneously:

**Terminal 1** (Azure AD):

```bash
cd dfp-poc
python pipelines/inference_pipeline.py  # Reads from dfp-events
```

**Terminal 2** (E-commerce):

```bash
cd dfp-ecommerce
python pipelines/inference_pipeline.py  # Reads from ecommerce-events
```

**Shared Infrastructure**:

- Same Kafka broker (localhost:29092)
- Same MLflow server (localhost:5001)
- Different topics prevent cross-contamination
- Different cache directories prevent baseline collision

---

## APPLICATION INTEGRATION

### Event Logger

Create `dfp-ecommerce/scripts/event_logger.py`:

```python
from confluent_kafka import Producer
import json
from datetime import datetime, timezone

class EcommerceEventLogger:
    def __init__(self):
        self.producer = Producer({'bootstrap.servers': 'localhost:29092'})

    def log_event(self, email, event_type, metadata=None):
        """Log e-commerce event to Kafka for DFP."""
        event = {
            "email": email,
            "event_time": datetime.now(timezone.utc).isoformat() + "Z",
            "event_type": event_type,
            **(metadata or {})
        }
        self.producer.produce(
            'ecommerce-events',
            key=email.encode('utf-8'),
            value=json.dumps(event).encode('utf-8')
        )
        self.producer.poll(0)

event_logger = EcommerceEventLogger()
```

### Flask Integration

```python
from scripts.event_logger import event_logger
import hashlib

@app.route('/api/checkout', methods=['POST'])
def checkout():
    user_email = request.json['email']

    # Existing business logic
    order = process_checkout(...)
    db.session.add(order)
    db.session.commit()

    # NEW: Log to Kafka for DFP (non-blocking, comprehensive metadata)
    event_logger.log_event(
        email=user_email,
        event_type="checkout",
        metadata={
            "category": request.json['items'][0]['category'],
            "product_id": request.json['items'][0]['sku'],
            "payment_type": request.json['payment_method'],
            "device": get_device_type(request),
            "user_agent_browser": get_browser(request),
            "geo_country": get_country_from_ip(request.remote_addr),
            "shipping_address_hash": hash_address(request.json['shipping_address']),
            "billing_address_hash": hash_address(request.json['billing_address']),
            "promo_code": request.json.get('promo_code', ''),
            "order_value": request.json['total'],
            "is_guest_checkout": not current_user.is_authenticated,
            "session_duration": get_session_duration(),
            "page_views": session.get('page_view_count', 0)
        }
    )

    return jsonify({"order_id": order.id})


@app.route('/api/refund', methods=['POST'])
def refund():
    """Log refund requests for fraud detection."""
    user_email = request.json['email']

    # Business logic
    refund = process_refund(...)

    # Log to DFP
    event_logger.log_event(
        email=user_email,
        event_type="refund",
        metadata={
            "order_id": request.json['order_id'],
            "category": refund.product_category,
            "order_value": refund.amount,
            "days_since_purchase": (datetime.now() - refund.order_date).days
        }
    )
    return jsonify({"refund_id": refund.id})


@app.route('/api/review', methods=['POST'])
def submit_review():
    """Log review submissions for fake review detection."""
    user_email = request.json['email']

    # Business logic
    review = save_review(...)

    # Log to DFP
    event_logger.log_event(
        email=user_email,
        event_type="review",
        metadata={
            "product_id": request.json['product_id'],
            "category": get_product_category(request.json['product_id']),
            "review_length": len(request.json['review_text']),
            "rating": request.json['rating']
        }
    )
    return jsonify({"review_id": review.id})


@app.route('/api/gift-card/check', methods=['POST'])
def check_gift_card():
    """Log gift card balance checks for carding detection."""
    user_email = request.json.get('email', 'anonymous')

    # Business logic
    balance = get_gift_card_balance(request.json['card_number'])

    # Log to DFP
    event_logger.log_event(
        email=user_email,
        event_type="gift_card_check",
        metadata={
            "card_valid": balance is not None,
            "device": get_device_type(request),
            "geo_country": get_country_from_ip(request.remote_addr)
        }
    )
    return jsonify({"balance": balance if balance else 0})


def hash_address(address_dict):
    """Hash address for privacy while detecting changes."""
    address_str = f"{address_dict['street']}|{address_dict['city']}|{address_dict['postal_code']}"
    return hashlib.sha256(address_str.encode()).hexdigest()[:16]
```

---

## THREAT DETECTION

### 1. Account Takeover (ATO)

**Pattern**: Credential stuffing or session hijacking

```python
# Attacker logs in from new location with different device
logcount: 150 → 151
locincrement: 1 → 2        # NEW COUNTRY (UK → Russia)
device_type: "desktop"      # User normally uses mobile
browser: "Firefox"          # User normally uses Chrome
action: "login" → "checkout" # Immediate high-value purchase
→ z-score: 5.23 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 4.0:
    require_mfa(detection['user_id'])
    send_email_alert(detection['user_id'], "Unusual login detected")
    temporary_account_lock(detection['user_id'])
```

---

### 2. Inventory Hoarding Bots

**Pattern**: Rapid cart additions across many categories without checkout

```python
# Bot adds high-demand items to cart to create artificial scarcity
logcount: 50 → 150          # 100 events in 5 minutes
productincrement: 5 → 15    # Accessing 10 categories rapidly
action: "add_to_cart" (repeated 100 times)
checkout_count: 0           # No purchases completed
session_duration: 120s      # Very short time
→ z-score: 6.78 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 5.0 and rapid_cart_adds:
    require_captcha(detection['user_id'])
    release_cart_items(detection['user_id'])
    rate_limit_ip(detection['ip_address'])
```

---

### 3. Card Testing Fraud

**Pattern**: Multiple payment methods tested with small transactions

```python
# Fraudster testing stolen card numbers
paymentincrement: 1 → 5     # 4 NEW PAYMENT METHODS in 10 minutes
logcount: 150 → 165         # 15 rapid payment attempts
action: "payment" (repeated)
order_value: £1.00 (all transactions) # Small test amounts
payment_success_rate: 20%   # Most declined
→ z-score: 7.12 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 6.0 and multiple_payment_methods:
    block_account(detection['user_id'])
    flag_payment_methods_for_review()
    notify_fraud_team(detection)
```

---

### 4. Promo Code Abuse

**Pattern**: Testing many promo codes to find valid ones

```python
# User trying leaked/generated promo codes
promoincrement: 1 → 20      # 19 different promo codes tested
logcount: 200 → 220         # Rapid checkout attempts
action: "checkout" (repeated with different codes)
promo_success_rate: 5%      # Most invalid
session_duration: 180s      # Short focused session
→ z-score: 5.89 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 5.0 and high_promo_testing:
    limit_promo_attempts(detection['user_id'])
    invalidate_leaked_codes()
    require_account_verification(detection['user_id'])
```

---

### 5. Serial Return Fraud (Wardrobing)

**Pattern**: High refund rate, especially for high-value items

```python
# User ordering and returning items after use
refundcount: 5 → 10         # 5 new refunds in 30 days
purchase_count: 15          # 10 out of 15 orders refunded (67%)
product_category: "Clothing" (all refunds)
order_value_avg: £150       # High-value items
time_to_refund_avg: 13 days # Just before 14-day return window
→ z-score: 6.45 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 6.0 and high_refund_rate:
    flag_for_manual_review(detection['user_id'])
    require_return_photo_proof(detection['user_id'])
    limit_future_returns(detection['user_id'])
```

---

### 6. Shipping Address Fraud

**Pattern**: Frequent shipping address changes, especially with new payment methods

```python
# Fraudster using stolen cards with different drop addresses
shippingincrement: 2 → 7    # 5 different addresses in 7 days
paymentincrement: 1 → 3     # 2 new payment methods
locincrement: 1 → 1         # Same country (not traveling)
billing_shipping_mismatch: true # Addresses don't match
is_guest_checkout: true     # No account history
→ z-score: 5.67 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 5.0 and address_velocity_high:
    hold_shipment(detection['order_id'])
    require_id_verification(detection['user_id'])
    verify_payment_method_ownership()
```

---

### 7. Fake Review Campaigns

**Pattern**: Unusual review activity, especially from new accounts

```python
# Competitor or paid reviewer posting fake reviews
reviewcount: 0 → 15         # 15 reviews submitted in 24 hours
logcount: 20 → 35           # Low overall activity
purchase_count: 2           # Only 2 purchases, 15 reviews
productincrement: 10 → 20   # Reviewing 10 different categories
review_length_avg: 50       # Short, generic reviews
→ z-score: 6.91 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 6.0 and suspicious_reviews:
    flag_reviews_for_moderation(detection['user_id'])
    require_verified_purchase_badge()
    temporarily_hide_reviews(detection['user_id'])
```

---

### 8. Gift Card Balance Checking (Carding)

**Pattern**: Rapid gift card balance checks with no purchases

```python
# Fraudster checking stolen gift card balances
logcount: 300 → 350         # 50 events in 10 minutes
action: "gift_card_check" (repeated 50 times)
payment_method: "gift_card" (all attempts)
balance_check_success_rate: 10% # Most invalid
checkout_count: 0           # No actual purchases
session_duration: 600s      # Short session
→ z-score: 8.12 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 7.0 and gift_card_abuse:
    block_ip_address(detection['ip_address'])
    rate_limit_gift_card_checks()
    invalidate_compromised_cards()
    require_captcha_for_balance_checks()
```

---

### 9. Cart Abandonment Abuse

**Pattern**: Creating fake demand by reserving inventory without purchasing

```python
# Bot creating artificial scarcity for high-demand items
logcount: 100 → 200         # 100 cart events
action: "add_to_cart" (90% of actions)
checkout_count: 0           # No checkouts
product_category: "Electronics" (limited stock items)
cart_size_avg: 10 items     # Large carts
session_count: 20           # Multiple sessions
→ z-score: 6.23 (ANOMALY)
```

**Response**:

```python
if detection['anomaly_score'] > 5.5 and cart_abuse_pattern:
    reduce_cart_reservation_time(detection['user_id'])
    release_cart_items_early(detection['user_id'])
    require_account_for_cart_holds()
```

---

## DEPLOYMENT CHECKLIST

### Pre-Deployment

- [ ] Copy dfp-poc to dfp-ecommerce
- [ ] Customize `feature_schema.yaml` (e-commerce features)
- [ ] Update `base_config.yaml` (Kafka topics, cache path)
- [ ] Create Kafka topics

### Training

- [ ] Collect 3+ months historical data (>300 events/user)
- [ ] Run training pipeline
- [ ] Verify models in MLflow (<http://localhost:5001>)

### Application

- [ ] Create event logger module
- [ ] Integrate in checkout, login, cart endpoints
- [ ] Monitor Kafka topic (kafka-console-consumer)

### Inference

- [ ] Start inference pipeline
- [ ] Monitor terminal output (z-scores)
- [ ] Subscribe to ecommerce-detections topic
- [ ] Integrate alerts (MFA, CAPTCHA, blocks)

### Testing

- [ ] Simulate normal behavior
- [ ] Simulate anomalies
- [ ] Tune threshold if needed

---

## KEY DIFFERENCES SUMMARY

### Reused from dfp-poc (95%)

✅ All pipeline code (`training_pipeline.py`, `inference_pipeline.py`)
✅ All modules (`preprocessing/`, `training/`, `inference/`)
✅ Infrastructure (`services/start_services.sh`)
✅ NVIDIA architecture pattern

### Customized for e-commerce (5%)

🔧 `config/feature_schema.yaml` (e-commerce events + productincrement, paymentincrement)
🔧 `config/base_config.yaml` (different Kafka topics, cache path)
🔧 Application event logger (Kafka producer)

---

## TROUBLESHOOTING

### Models Not Found

```bash
# Check MLflow
curl http://localhost:5001/api/2.0/mlflow/experiments/list

# Retrain if missing
python pipelines/training_pipeline.py --data-path data/input/historical.csv
```

### Excessive Anomaly Flags

Increase threshold in `base_config.yaml`:

```yaml
kafka:
  streaming:
    anomaly_threshold: 3.0 # From 2.0
```

### Cache Collision

Verify separate directories:

```bash
ls dfp-poc/data/.cache/dfp/rolling-user-data/
ls dfp-ecommerce/data/.cache/dfp-ecommerce/rolling-user-data/
```

---

## THREAT-TO-FEATURE MAPPING

Quick reference showing which behavioral features detect each threat:

| Threat                 | Primary Detection Features                                              | Supporting Features                   | Response Action                  |
| ---------------------- | ----------------------------------------------------------------------- | ------------------------------------- | -------------------------------- |
| **Account Takeover**   | `locincrement` (new country), `device_type`, `browser` (new device)     | `logcount` (sudden activity)          | Require MFA, lock account        |
| **Inventory Hoarding** | `logcount` (rapid spike), `productincrement` (many categories)          | `action` (cart adds without checkout) | CAPTCHA, release cart            |
| **Card Testing**       | `paymentincrement` (multiple cards), `logcount` (rapid attempts)        | `order_value` (small amounts)         | Block account, flag cards        |
| **Promo Abuse**        | `promoincrement` (many codes tested)                                    | `logcount` (rapid checkouts)          | Limit attempts, invalidate codes |
| **Return Fraud**       | `refundcount` (high refund rate)                                        | `order_value`, `product_category`     | Manual review, require proof     |
| **Shipping Fraud**     | `shippingincrement` (address changes), `paymentincrement` (new payment) | `locincrement` (same country)         | Hold shipment, verify ID         |
| **Fake Reviews**       | `reviewcount` (review spike), `productincrement` (many categories)      | `logcount` (low activity)             | Flag for moderation              |
| **Gift Card Fraud**    | `logcount` (rapid checks), `action` (gift_card_check)                   | `paymentincrement`                    | Block IP, rate limit             |
| **Cart Abandonment**   | `logcount` (high cart adds), `action` (no checkouts)                    | `productincrement`                    | Reduce reservation time          |

**Key Insight**: All threats are detected using **NVIDIA standard increment features** (IncrementColumn, DistinctIncrementColumn). The same DFP architecture detects different threats by learning **normal patterns per user**.

---

## FEATURE ENGINEERING BEST PRACTICES

### Privacy-Preserving Features

**Hash Sensitive Data**:

```python
# Don't store raw addresses - use hashes
shipping_address_hash = hashlib.sha256(f"{street}|{city}|{postal}".encode()).hexdigest()[:16]

# Don't store card numbers - use last 4 digits + bin
payment_identifier = f"{card_bin}_{last4}"
```

**Why**: Detects changes (address fraud, payment testing) without storing PII.

### Time-Based Features

**Session Duration** (detects bot behavior):

```python
session_duration = (logout_time - login_time).total_seconds()
# Bots: Very short (<60s) or very long (>3600s) sessions
```

**Time to Action** (detects rushed fraud):

```python
time_to_checkout = (checkout_time - login_time).total_seconds()
# Fraud: Immediate checkout after login (<30s)
```

### Ratio Features

**Refund Rate** (calculated in preprocessing):

```python
refund_rate = refundcount / purchase_count
# Wardrobing: >50% refund rate
```

**Promo Success Rate**:

```python
promo_success_rate = successful_promos / promoincrement
# Abuse: <10% success (testing leaked codes)
```

### Excluded Features (Not Used)

Don't include in model training:

- `transaction_amount` - Biases model (fraud amounts vary)
- `product_id` - Too high cardinality (millions of SKUs)
- `ip_address` - PII, use derived feature (`country`)
- `session_id` - Session-specific, not user-specific
- `promo_code` - High cardinality, use `promoincrement` counter

**Why**: High-cardinality features cause overfitting. DFP learns **behavioral patterns**, not specific values.

---

## CONCLUSION

**What You've Achieved**:
✅ Extended DFP to e-commerce without modifying existing Azure AD implementation
✅ Reused 95% of code (only config customization)
✅ Parallel operation (both run simultaneously)
✅ Production-ready (NVIDIA-compliant)

**Benefits**:

- Non-invasive (application DB unchanged, dual-write to Kafka)
- Real-time (100-500ms latency)
- Per-user learning (adapts to individual behavior)
- Unsupervised (no labeled data needed)

**Next Steps**:

1. Collect historical e-commerce data
2. Train initial models
3. Integrate event logger in application
4. Deploy inference pipeline
5. Monitor and tune threshold

**References**:

- Your base: `dfp-poc/`
- NVIDIA docs: <https://docs.nvidia.com/morpheus>
- Services: `dfp-poc/services/README.md`
