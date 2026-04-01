-- Stripe Connect V1 schema changes
-- Compatible with PostgreSQL / SQLite-like syntax for simple rollout.

ALTER TABLE coach_settings ADD COLUMN stripe_account_id VARCHAR(64);
ALTER TABLE coach_settings ADD COLUMN stripe_onboarding_state VARCHAR(24) DEFAULT 'not_connected';
ALTER TABLE coach_settings ADD COLUMN stripe_details_submitted BOOLEAN DEFAULT FALSE;
ALTER TABLE coach_settings ADD COLUMN stripe_charges_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE coach_settings ADD COLUMN stripe_payouts_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE coach_settings ADD COLUMN stripe_last_synced_at TIMESTAMP;

ALTER TABLE slots ADD COLUMN stripe_payment_intent_id VARCHAR(128);
ALTER TABLE slots ADD COLUMN stripe_checkout_session_id VARCHAR(128);
ALTER TABLE slots ADD COLUMN stripe_payment_status VARCHAR(24) DEFAULT 'not_started';

CREATE TABLE payment_transactions (
  id SERIAL PRIMARY KEY,
  slot_id INTEGER NOT NULL,
  coach_id INTEGER NOT NULL,
  patient_user_id INTEGER NOT NULL,
  stripe_account_id VARCHAR(64) NOT NULL,
  stripe_checkout_session_id VARCHAR(128),
  stripe_payment_intent_id VARCHAR(128),
  amount_cents INTEGER NOT NULL,
  currency VARCHAR(8) NOT NULL DEFAULT 'eur',
  status VARCHAR(24) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

CREATE INDEX idx_payment_transactions_slot_id ON payment_transactions(slot_id);
CREATE INDEX idx_payment_transactions_pi ON payment_transactions(stripe_payment_intent_id);
CREATE INDEX idx_payment_transactions_checkout ON payment_transactions(stripe_checkout_session_id);
