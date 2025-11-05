toryfrom src.services.statement_service import StatementService
from datetime import datetime, timezone

# Test statement generation
service = StatementService()

# Use associate ID 1 (stefano) and today's cutoff
associate_id = 1
cutoff_date = datetime.now(timezone.utc).strftime("%Y-%m-%dT23:59:59Z")

print(f"Testing statement generation for associate {associate_id} with cutoff {cutoff_date}")

try:
    calc = service.generate_statement(associate_id, cutoff_date)
    print(f"✅ Statement generated successfully!")
    print(f"   Associate: {calc.associate_name}")
    print(f"   Net Deposits: €{calc.net_deposits_eur:,.2f}")
    print(f"   Should Hold: €{calc.should_hold_eur:,.2f}")
    print(f"   Current Holding: €{calc.current_holding_eur:,.2f}")
    print(f"   Raw Profit: €{calc.raw_profit_eur:,.2f}")
    print(f"   Delta: €{calc.delta_eur:,.2f}")
    
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
