/** Mirrors the backend OpenAPI schema for `GET /crossings/{slug}/status`. */

export type GateState = 'open' | 'closed' | 'closing_soon';

export interface CrossingSummary {
  slug: string;
  name: string;
  city: string | null;
  state: string | null;
  latitude: number;
  longitude: number;
  line_name: string | null;
  up_towards: string | null;
  down_towards: string | null;
}

export interface TrainCause {
  train_number: string;
  train_name: string;
  train_class: string;
  direction: 'up' | 'down' | 'unknown';
  pass_at: string;
  speed_kmph: number;
  delay_minutes: number;
  provider: string;
  estimator: string;
}

export interface ClosureWindow {
  close_at: string;
  open_at: string;
  duration_seconds: number;
  confidence: number;
  causes: TrainCause[];
}

export interface Confidence {
  score: number;
  label: string;
  factors: Record<string, number>;
  notes: string[];
}

export interface ApproachingTrain {
  train_number: string;
  train_name: string;
  train_class: string;
  direction: 'up' | 'down' | 'unknown';
  pass_at: string;
  speed_kmph: number;
  delay_minutes: number;
}

export interface TodaySummary {
  date: string;
  closure_count: number;
  total_closed_seconds: number;
  longest_closure_seconds: number;
  closures: ClosureWindow[];
}

export interface DataQuality {
  providers_used: string[];
  degraded: boolean;
  stale: boolean;
  freight_risk: number;
  last_updated_at: string | null;
  notes: string[];
}

export interface LeaveAdvice {
  travel_seconds: number;
  arrival_at: string;
  can_cross: boolean;
  verdict: 'go' | 'tight' | 'wait';
  reason: string;
}

export interface CrossingStatus {
  crossing: CrossingSummary;
  generated_at: string;
  server_time: string;
  state: GateState;
  seconds_until_close: number | null;
  seconds_until_open: number | null;
  current_closure: ClosureWindow | null;
  next_closure: ClosureWindow | null;
  upcoming: ClosureWindow[];
  approaching_train: ApproachingTrain | null;
  confidence: Confidence;
  today: TodaySummary;
  data: DataQuality;
  advice: LeaveAdvice | null;
}
