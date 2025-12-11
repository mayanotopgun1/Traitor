use super::framework::Mutator;
use syn::visit::{self, Visit};
use syn::visit_mut::{self, VisitMut};
use syn::{ExprBinary, BinOp, ExprLit, Lit};
use syn::parse_quote;

// =========================================================================
// 1. Binary Operator Flip
// =========================================================================

pub struct BinOpFlipMutator;

// Helper to define supported operators and avoid duplication
fn is_supported_bin_op(op: &BinOp) -> bool {
    matches!(
        op,
        BinOp::Add(_) | BinOp::Sub(_) | BinOp::Mul(_) | BinOp::Div(_) |
        BinOp::Rem(_) | BinOp::And(_) | BinOp::Or(_) |
        BinOp::BitAnd(_) | BinOp::BitOr(_) | BinOp::BitXor(_) |
        BinOp::Shl(_) | BinOp::Shr(_)
    )
}

// Helper to get a random DIFFERENT operator
fn get_random_bin_op(current_op: &BinOp) -> BinOp {
    use rand::seq::SliceRandom;
    let all_ops: Vec<BinOp> = vec![
        BinOp::Add(Default::default()),
        BinOp::Sub(Default::default()),
        BinOp::Mul(Default::default()),
        BinOp::Div(Default::default()),
        BinOp::Rem(Default::default()),
        BinOp::And(Default::default()),
        BinOp::Or(Default::default()),
        BinOp::BitAnd(Default::default()),
        BinOp::BitOr(Default::default()),
        BinOp::BitXor(Default::default()),
        BinOp::Shl(Default::default()),
        BinOp::Shr(Default::default()),
    ];
    
    let current_discriminant = std::mem::discriminant(current_op);
    let choices: Vec<&BinOp> = all_ops.iter()
        .filter(|op| std::mem::discriminant(*op) != current_discriminant)
        .collect();

    let mut rng = rand::thread_rng();
    choices.choose(&mut rng).cloned().cloned().unwrap_or_else(|| all_ops[0].clone())
}

struct BinOpFlipCollector { count: usize }
impl<'ast> Visit<'ast> for BinOpFlipCollector {
    fn visit_expr_binary(&mut self, i: &'ast ExprBinary) {
        if is_supported_bin_op(&i.op) {
            self.count += 1;
        }
        visit::visit_expr_binary(self, i);
    }
}

struct BinOpFlipApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for BinOpFlipApplier {
    fn visit_expr_binary_mut(&mut self, i: &mut ExprBinary) {
        if is_supported_bin_op(&i.op) {
            if self.current == self.target {
                i.op = get_random_bin_op(&i.op);
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_expr_binary_mut(self, i);
    }
}

impl Mutator for BinOpFlipMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = BinOpFlipCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = BinOpFlipApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 2. Int Literal Change
// =========================================================================
pub struct IntLiteralChangeMutator;

struct IntLitCollector { count: usize }
impl<'ast> Visit<'ast> for IntLitCollector {
    fn visit_expr_lit(&mut self, i: &'ast ExprLit) {
        if let Lit::Int(_) = &i.lit { self.count += 1; }
        visit::visit_expr_lit(self, i);
    }
}

struct IntLitApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for IntLitApplier {
    fn visit_expr_lit_mut(&mut self, i: &mut ExprLit) {
        if let Lit::Int(lit_int) = &i.lit {
            if self.current == self.target {
                 if let Ok(val) = lit_int.base10_parse::<i64>() {
                    let new_val = val.wrapping_add(1);
                    i.lit = Lit::Int(syn::LitInt::new(&new_val.to_string(), lit_int.span()));
                    self.mutated = true;
                }
            }
            self.current += 1;
        }
        visit_mut::visit_expr_lit_mut(self, i);
    }
}

impl Mutator for IntLiteralChangeMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = IntLitCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = IntLitApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 3. Bool Flip
// =========================================================================
pub struct BoolFlipMutator;

struct BoolFlipCollector { count: usize }
impl<'ast> Visit<'ast> for BoolFlipCollector {
    fn visit_expr_lit(&mut self, i: &'ast ExprLit) {
        if let Lit::Bool(_) = &i.lit { self.count += 1; }
        visit::visit_expr_lit(self, i);
    }
}

struct BoolFlipApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for BoolFlipApplier {
    fn visit_expr_lit_mut(&mut self, i: &mut ExprLit) {
        if let Lit::Bool(lit_bool) = &i.lit {
            if self.current == self.target {
                let new_val = !lit_bool.value;
                i.lit = Lit::Bool(syn::LitBool::new(new_val, lit_bool.span));
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_expr_lit_mut(self, i);
    }
}

impl Mutator for BoolFlipMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = BoolFlipCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = BoolFlipApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 4. Replace By Constant
// =========================================================================
pub struct ReplaceByConstantMutator;

struct ReplaceConstCollector { count: usize }
impl<'ast> Visit<'ast> for ReplaceConstCollector {
     fn visit_expr(&mut self, i: &'ast syn::Expr) {
         if let syn::Expr::Binary(_) = i { self.count += 1; }
         visit::visit_expr(self, i);
     }
}

struct ReplaceConstApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for ReplaceConstApplier {
    fn visit_expr_mut(&mut self, i: &mut syn::Expr) {
        if let syn::Expr::Binary(_) = i {
            if self.current == self.target {
                *i = parse_quote!(0);
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_expr_mut(self, i);
    }
}

impl Mutator for ReplaceByConstantMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = ReplaceConstCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = ReplaceConstApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 5. Inject Control Flow
// =========================================================================
pub struct InjectControlFlowMutator;

struct InjectFlowCollector { count: usize }
impl<'ast> Visit<'ast> for InjectFlowCollector {
    fn visit_block(&mut self, _: &'ast syn::Block) {
        self.count += 1;
    }
}

struct InjectFlowApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for InjectFlowApplier {
    fn visit_block_mut(&mut self, i: &mut syn::Block) {
        if self.current == self.target {
            let stmt: syn::Stmt = parse_quote!(let _injected = 0;);
            i.stmts.insert(0, stmt);
            self.mutated = true;
        }
        self.current += 1;
        visit_mut::visit_block_mut(self, i);
    }
}

impl Mutator for InjectControlFlowMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = InjectFlowCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = InjectFlowApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}
