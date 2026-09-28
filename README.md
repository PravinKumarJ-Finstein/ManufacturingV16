## Manufacturing Plus

Auto **Expected Delivery Date** on the Sales Order, and auto purchase of the missing raw
material — for ERPNext v16.

Built from `Manufacturing_App_Development_Spec_v16.pdf`.

### What it does

**On Sales Order save** — each line gets an Expected Delivery Date:

```
order date + RM lead days (longest SHORT component only)
           + queue days (work already committed on the same workstations)
           + production days (qty / capacity per hour / working hours per day, all operations)
           + buffer days
```

The date is always stored in `mp_expected_delivery_date`; `delivery_date` is filled only when the
user left it blank (configurable).

**On Sales Order submit** — background job:

1. a draft **Master Production Schedule** for that Sales Order (always, shortage or not),
2. the stock it consumes is **reserved** against that MPS, so the next MPS sees it as short,
3. the shortage is read from the core **MRP** calculation,
4. a draft **Material Request** (Purchase) for the short items, one line per Sales Order line,
5. a draft **Purchase Order** per supplier, created automatically from that Material Request.

**On Purchase Order submit** — the real date flows back: the Sales Order line is marked
`Confirmed`, or `At Risk` with the gap in days. A Purchase Receipt closes the demand row.

### Settings

Everything lives in **Manufacturing Control Setting** (Single), in four tabs: Delivery Date
Planning, Auto Purchase, Work Order & Pick List, Shop Floor & Quality. No number is hard-coded.

**Switching a feature off closes it completely.** Saving the setting:

* takes the role permissions away from that feature's doctypes, so the **list and the form refuse
  to open** and the doctype **disappears from the search bar**,
* blocks the document server-side through a `has_permission` hook and a guard in the controller,
  so the REST API is closed too,
* stops the hooks and the scheduled jobs behind it.

Switching it back on restores exactly the permissions the doctype itself defines — never more.
Existing records are untouched; they become reachable again the moment the feature is back on.

### Master data to fill

| Master | What |
|---|---|
| Workstation → Working Hours | gives hours per day |
| BOM | components and operations. **Throughput lives here**: `time_in_mins` per BOM qty, with `batch_size` for a rate (60 mins per 500 = 500/hour) or `fixed_time` for setup |
| Item Lead Time | `purchase_time` + `buffer_time` per purchased item |
| Item / Item Default | default supplier, MOQ, Item Price (buying) |

### Shop floor (carried over from the Kaynes v15 app)

Each one is switched by a field in the **Work Order & Pick List** or **Shop Floor & Quality** tab:

| Feature | What it does |
|---|---|
| Work Order source rule | A Work Order may only come from a Production Plan |
| Planned qty tracking | The Production Plan writes planned qty back to the Sales Order line |
| Pick List buffer | Extra qty per `Pick List Configuration` slab, added to the required items on submit |
| Job Card gates | No Job Card start without a submitted Pick List (and, optionally, a Job Setup Verification) |
| Pick List flow | Expired batches blocked, duplicate Pick List warning, Stock Entry created on submit |
| Spool / reel tracking | Spools are rows on their **Batch** (`Spool Details`, as in Kaynes). Scan on the Pick List, balance worked out from the documents, `Excess Issue Note` before over-issuing, `Stores Return` for the unused reel |
| Stale Work Order clean-up | Nightly at 02:00: delete old drafts, cancel Not Started — never one the shop floor has started |
| Job Setup Verification | Checklist per operation, loaded from `Job Setup Checklist` |
| Yield Entry | Inspected / accepted / defects, with the `Yield Summary` report |
| Can Build | Daily at 07:00: how many finished goods stock allows, and the limiting item |
| Combo Parts split | "Split Combo" on a Purchase Receipt: kit out, child items in, value neutral |

### DocTypes

Planning and purchasing: `Manufacturing Control Setting` ·
`Sales Order Material Demand` · `MPS Stock Reservation` · `Auto Purchase Run` ·
`Auto Purchase Exception`.

Shop floor: `MP Item Package` · `Pick List Configuration` · `Spool Details` (on Batch) · `Excess Issue Note` ·
`Stores Return` · `Job Setup Checklist` · `Job Setup Verification` · `Yield Entry` ·
`Combo Parts` · `Can Build Log` (+ child tables).

### Reports

* **Sales Order Purchase Coverage** — which PO covers which Sales Order line.
* **Purchase Order Demand Trace** — which Sales Order lines a PO line serves.
* **Yield Summary** — yield per Work Order and operation, worst first.

### v16 behaviour this app works around

* The auto-created MPS stays a **draft**: submitting one queues `make_mrp`, which does not exist in
  v16.34.2.
* The MPS `sales_orders` table is always filled, otherwise the MRP counts the same Sales Order twice
  as "Ad-hoc".
* The core MRP nets stock **in memory** and subtracts only Stock Reservation Entries, and an SRE
  cannot point at an MPS — hence the app's own `MPS Stock Reservation` ledger.
* The demand link fields on Material Request Item / Purchase Order Item are **Data, not Link**: a
  Link would stop a Sales Order being cancelled while a submitted MR exists.
* The core `Purchase Order Item.sales_order` (drop-ship) field is never set — it would shrink the
  Delivery Note qty on the Sales Order.

### Known limits

* Two **draft** Sales Orders saved at the same moment can still be promised the same stock and the
  same machine hours: the queue and the reservation only start at submit.
* MOQ rounding happens per Material Request line, so buying for two Sales Order lines of the same
  item can round up twice. Consolidation can be added later.
* Pick List buffer slabs are matched on the required qty of a single Work Order, so a demand split
  across several Work Orders is buffered once per order.

### Install

```bash
bench get-app manufacturing_plus <path-or-url>
bench --site <site> install-app manufacturing_plus
bench --site <site> migrate
```

### Tests

```bash
bench --site <site> run-tests --app manufacturing_plus
```

#### License

mit
