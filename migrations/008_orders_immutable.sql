-- Person 3 (008 is reserved for them; distinct name per migrations/README.md).
-- A saved receipt is history: block UPDATE and DELETE on orders, like the other history tables
-- (immutable_record() and its triggers are created in 001_initial.sql). Additive: no row,
-- column or constraint changes, so it is safe on a populated database; DROP IF EXISTS keeps it
-- repeatable. Nothing in the application updates or deletes orders; proposals.order_id stays
-- mutable because it is the pointer set once at commit.
DROP TRIGGER IF EXISTS immutable_orders ON orders;
CREATE TRIGGER immutable_orders BEFORE UPDATE OR DELETE ON orders
 FOR EACH ROW EXECUTE FUNCTION immutable_record();
