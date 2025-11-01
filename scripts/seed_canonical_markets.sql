-- Canonical Markets - Comprehensive Coverage
-- Run this to seed all common betting markets
-- Usage: sqlite3 data/surebet.db < scripts/seed_canonical_markets.sql

-- Clear existing markets (optional - uncomment if reseeding)
-- DELETE FROM canonical_markets;

-- TIER 1: MOST COMMON MARKETS (Football/Soccer)
-- These cover ~80% of betting volume
INSERT OR IGNORE INTO canonical_markets (market_code, description) VALUES
-- Match outcomes
('MATCH_WINNER', 'Match Winner / 1X2 / Moneyline'),
('DRAW_NO_BET', 'Draw No Bet'),
('DOUBLE_CHANCE', 'Double Chance (1X, X2, 12)'),

-- Goals markets
('TOTAL_GOALS_OVER_UNDER', 'Total Goals Over/Under'),
('BOTH_TEAMS_TO_SCORE', 'Both Teams to Score (BTTS)'),
('TEAM_TOTAL_GOALS', 'Team Total Goals Over/Under'),

-- Handicaps
('ASIAN_HANDICAP', 'Asian Handicap'),
('EUROPEAN_HANDICAP', 'European Handicap / 3-Way Handicap'),

-- Halves
('HALF_TIME_RESULT', 'Half Time Result (1X2)'),
('HALF_TIME_FULL_TIME', 'Half Time / Full Time'),
('SECOND_HALF_WINNER', 'Second Half Winner');

-- TIER 2: POPULAR MARKETS (Football/Soccer)
-- Cover next ~15% of betting volume
INSERT OR IGNORE INTO canonical_markets (market_code, description) VALUES
-- Goals timing
('FIRST_GOAL_SCORER', 'First Goal Scorer'),
('LAST_GOAL_SCORER', 'Last Goal Scorer'),
('ANYTIME_GOAL_SCORER', 'Anytime Goal Scorer'),
('FIRST_HALF_GOALS_OU', 'First Half Goals Over/Under'),
('SECOND_HALF_GOALS_OU', 'Second Half Goals Over/Under'),

-- Exact scores
('CORRECT_SCORE', 'Correct Score'),
('WINNING_MARGIN', 'Winning Margin'),

-- Other popular
('TOTAL_CORNERS', 'Total Corners Over/Under'),
('TOTAL_CARDS', 'Total Cards Over/Under'),
('CLEAN_SHEET', 'To Keep a Clean Sheet'),
('TO_WIN_TO_NIL', 'To Win to Nil');

-- TIER 3: NICHE MARKETS (Football/Soccer)
-- Cover remaining ~5% and specialist bets
INSERT OR IGNORE INTO canonical_markets (market_code, description) VALUES
-- Corners
('CORNER_HANDICAP', 'Corner Handicap'),
('FIRST_CORNER', 'First Corner'),
('CORNER_MATCH_BET', 'Corner Match Bet'),

-- Cards
('TOTAL_BOOKINGS', 'Total Booking Points'),
('PLAYER_TO_BE_BOOKED', 'Player to be Booked'),
('SENDING_OFF', 'Sending Off / Red Card'),

-- Goals details
('ODD_EVEN_GOALS', 'Odd/Even Total Goals'),
('GOALS_IN_BOTH_HALVES', 'Goals Scored in Both Halves'),
('TEAM_TO_SCORE_FIRST', 'Team to Score First'),
('TEAM_TO_SCORE_LAST', 'Team to Score Last'),
('NEXT_GOAL', 'Next Goal'),

-- Minutes
('GOAL_IN_FIRST_10MIN', 'Goal in First 10 Minutes'),
('TIME_OF_FIRST_GOAL', 'Time of First Goal'),

-- Specials
('HAT_TRICK', 'Hat-Trick Scored'),
('PENALTY_AWARDED', 'Penalty to be Awarded'),
('OWN_GOAL', 'Own Goal to be Scored');

-- TIER 4: OTHER SPORTS MARKETS
INSERT OR IGNORE INTO canonical_markets (market_code, description) VALUES
-- Tennis
('TENNIS_MATCH_WINNER', 'Tennis - Match Winner'),
('TENNIS_SET_BETTING', 'Tennis - Correct Score in Sets'),
('TENNIS_TOTAL_GAMES', 'Tennis - Total Games Over/Under'),
('TENNIS_HANDICAP_GAMES', 'Tennis - Handicap Games'),

-- Basketball
('BASKETBALL_MONEYLINE', 'Basketball - Moneyline / Match Winner'),
('BASKETBALL_HANDICAP', 'Basketball - Point Spread / Handicap'),
('BASKETBALL_TOTAL_POINTS', 'Basketball - Total Points Over/Under'),
('BASKETBALL_FIRST_HALF', 'Basketball - First Half Winner'),
('BASKETBALL_QUARTER_WINNER', 'Basketball - Quarter Winner'),

-- American Football
('NFL_MONEYLINE', 'NFL - Moneyline'),
('NFL_SPREAD', 'NFL - Point Spread'),
('NFL_TOTAL_POINTS', 'NFL - Total Points Over/Under'),

-- Baseball
('BASEBALL_MONEYLINE', 'Baseball - Moneyline'),
('BASEBALL_RUN_LINE', 'Baseball - Run Line'),
('BASEBALL_TOTAL_RUNS', 'Baseball - Total Runs Over/Under'),

-- Ice Hockey
('HOCKEY_MONEYLINE', 'Hockey - Moneyline'),
('HOCKEY_PUCK_LINE', 'Hockey - Puck Line'),
('HOCKEY_TOTAL_GOALS', 'Hockey - Total Goals Over/Under'),

-- Other sports
('BOXING_METHOD_OF_VICTORY', 'Boxing - Method of Victory'),
('MMA_METHOD_OF_VICTORY', 'MMA - Method of Victory'),
('GOLF_TOURNAMENT_WINNER', 'Golf - Tournament Winner'),
('ESPORTS_MATCH_WINNER', 'Esports - Match Winner'),
('ESPORTS_MAP_HANDICAP', 'Esports - Map Handicap');

-- TIER 5: CATCH-ALL
INSERT OR IGNORE INTO canonical_markets (market_code, description) VALUES
('OTHER', 'Other / Unclassified Market'),
('CUSTOM', 'Custom Market');

-- Display summary
SELECT 'Market seeding complete!' as status;
SELECT COUNT(*) as total_markets FROM canonical_markets;
SELECT 'Sample markets:' as info;
SELECT market_code, description FROM canonical_markets ORDER BY id LIMIT 10;
