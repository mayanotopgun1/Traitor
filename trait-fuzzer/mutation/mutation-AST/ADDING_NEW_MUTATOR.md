# How to Add a New Mutator

We have standardized the mutation engine architecture. All mutators now follow a uniform **Collect -> Select -> Mutate** pipeline managed by the `Mutator` trait. This guide explains how to add a new one.

## 1. The Architecture
Every mutator consists of three components:
1.  **Collector**: Traverses the AST (read-only) to count how many possible mutation points exist.
2.  **Applier**: Traverses the AST (mutable) to apply the mutation at a specific selected index.
3.  **Mutator Impl**: The glue code that implements the `Mutator` trait to orchestrate the process.

## 2. Step-by-Step Implementation

### Step 1: Define Structs
In `src/mutators/structural.rs` or `src/mutators/non_structural.rs`, define your structures.

```rust
// The main unit struct for the mutator strategy
pub struct MyNewMutator;

// The collector struct (usually just needs a counter)
struct MyNewCollector { count: usize }

// The applier struct (needs target index, current index, and success flag)
struct MyNewApplier { target: usize, current: usize, mutated: bool }
```

### Step 2: Implement `Visit` for Collector
Implement `syn::visit::Visit` for your *Collector*. This defines **what** you are looking for.

```rust
use syn::visit::{self, Visit};

impl<'ast> Visit<'ast> for MyNewCollector {
    fn visit_expr_binary(&mut self, i: &'ast syn::ExprBinary) {
        // Condition: Is this a node we want to mutate?
        if let syn::BinOp::Add(_) = i.op {
            self.count += 1;
        }
        // IMPORTANT: Always call the default visit method to recurse into children!
        visit::visit_expr_binary(self, i);
    }
}
```

### Step 3: Implement `VisitMut` for Applier
Implement `syn::visit_mut::VisitMut` for your *Applier*. This defines **how** you change the code.

```rust
use syn::visit_mut::{self, VisitMut};
use syn::parse_quote;

impl VisitMut for MyNewApplier {
    fn visit_expr_binary_mut(&mut self, i: &mut syn::ExprBinary) {
        if let syn::BinOp::Add(_) = i.op {
            // Check if this is the instance selected by the distinct random number generator
            if self.current == self.target {
                // PERFORM MUTATION
                i.op = syn::BinOp::Sub(parse_quote!(-));
                self.mutated = true;
            }
            // Increment current counter
            self.current += 1;
        }
        // Recurse
        visit_mut::visit_expr_binary_mut(self, i);
    }
}
```

### Step 4: Implement `Mutator` Trait
Implement the standardized `Mutator` trait (imported from `super::framework::Mutator`) to verify the interface. This boilerplate is almost always the same.

```rust
use super::framework::Mutator;

impl Mutator for MyNewMutator {
    // 1. Collect Phase
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = MyNewCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }

    // 2. Mutate Phase
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = MyNewApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}
```

### Step 5: Register in `main.rs`
Finally, add your new mode string to the `match` block in `src/main.rs` so the CLI can call it.

```rust
// src/main.rs

match args.mode.as_str() {
    // ...
    "my_new_mutation" => MyNewMutator.run(&mut syntax_tree),
    // ...
}
```

## Checklist
- [ ] structs defined (`Mutator`, `Collector`, `Applier`)
- [ ] `Visit` implemented (don't forget `visit::visit_...` recursion!)
- [ ] `VisitMut` implemented (check `self.current == self.target`)
- [ ] `Mutator` trait implemented
- [ ] Added to `src/main.rs` switch case
