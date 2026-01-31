// =========================================================================
// LIFETIME MUTATION (MutationⅣ)
// =========================================================================
use super::framework::Mutator;
use syn::visit::{self, Visit};
use syn::visit_mut::{self, VisitMut};
use syn::{parse_quote, GenericParam, Ident, ImplItemFn, ItemFn, Signature, Type, TypeReference};

pub struct LifetimeMutator;

struct LifetimeCollector {
    count: usize,
    in_trait_impl: bool,
}

impl<'ast> Visit<'ast> for LifetimeCollector {
    fn visit_item_impl(&mut self, i: &'ast syn::ItemImpl) {
        let old_in_trait = self.in_trait_impl;
        if i.trait_.is_some() {
            self.in_trait_impl = true;
        }
        visit::visit_item_impl(self, i);
        self.in_trait_impl = old_in_trait;
    }

    fn visit_item_fn(&mut self, i: &'ast ItemFn) {
        // Top level functions always valid candidates
        for _input in &i.sig.inputs {
            self.count += 1;
        }
        visit::visit_item_fn(self, i);
    }

    fn visit_impl_item_fn(&mut self, i: &'ast ImplItemFn) {
        if !self.in_trait_impl {
            for _input in &i.sig.inputs {
                self.count += 1;
            }
        }
        visit::visit_impl_item_fn(self, i);
    }
}

struct LifetimeApplier {
    target: usize,
    current: usize,
    mutated: bool,
    in_trait_impl: bool,
}

impl LifetimeApplier {
    /// Modify the specific argument at the current index.
    /// Also ensures the function signature has the required lifetime parameter.
    fn try_mutate_arg(&mut self, sig: &mut Signature, arg_idx: usize) {
        // 1. Ensure a lifetime parameter exists.
        let mut target_lifetime = None;
        for p in &sig.generics.params {
            if let GenericParam::Lifetime(l) = p {
                target_lifetime = Some(l.lifetime.clone());
                break;
            }
        }
        
        if target_lifetime.is_none() {
            let new_lt: syn::Lifetime = parse_quote!('mut_lt);
            sig.generics.params.insert(0, parse_quote!(#new_lt));
            target_lifetime = Some(new_lt);
        }
        let lt = target_lifetime.unwrap();

        // 2. Mutate the specific argument `arg_idx`
        if let Some(input) = sig.inputs.iter_mut().nth(arg_idx) {
             match input {
                syn::FnArg::Receiver(r) => {
                    // self -> &self or &mut self
                    // If it's `self` (value), make it `&'lt self`
                    // If it's `&self`, make it `&'lt self`
                    if r.reference.is_none() {
                        r.reference = Some((parse_quote!(&), Some(lt.clone())));
                    } else {
                        if let Some(ref mut p) = r.reference {
                             p.1 = Some(lt.clone());
                        }
                    }
                },
                syn::FnArg::Typed(pat_type) => {
                    // Check if reference
                    if let Type::Reference(tr) = &mut *pat_type.ty {
                        // Already ref: inject lifetime
                        tr.lifetime = Some(lt.clone());
                    } else {
                        // Value type: wrap in reference &'lt T
                        // Deterministic: Always mutable reference? Or immutable?
                        // Let's go with immutable by default for broader compatibility, or maybe just &T.
                        // Actually, Mutation 2/3 style implies we might even want choices here, 
                        // but for now let's stick to "Wrap in &T" as the single deterministic action for a value type.
                        
                        let old_ty = *pat_type.ty.clone();
                        let new_ty = Type::Reference(TypeReference {
                            and_token: parse_quote!(&),
                            lifetime: Some(lt.clone()),
                            mutability: None, // Just &T to be safe-ish
                            elem: Box::new(old_ty),
                        });
                        *pat_type.ty = new_ty;
                    }
                }
            }
        }
    }
}

impl VisitMut for LifetimeApplier {
    fn visit_item_impl_mut(&mut self, i: &mut syn::ItemImpl) {
        let old_in_trait = self.in_trait_impl;
        if i.trait_.is_some() {
            self.in_trait_impl = true;
        }
        visit_mut::visit_item_impl_mut(self, i);
        self.in_trait_impl = old_in_trait;
    }

    fn visit_item_fn_mut(&mut self, i: &mut ItemFn) {
        if self.mutated { return; }
        
        // Check args
        let arg_count = i.sig.inputs.len();
        if self.current + arg_count > self.target {
            // Target is in this function
            let relative_idx = self.target - self.current;
            self.try_mutate_arg(&mut i.sig, relative_idx);
            self.mutated = true;
        }
        self.current += arg_count;
        
        visit_mut::visit_item_fn_mut(self, i);
    }

    fn visit_impl_item_fn_mut(&mut self, i: &mut ImplItemFn) {
        if self.mutated { return; }
        
        if !self.in_trait_impl {
            let arg_count = i.sig.inputs.len();
            if self.current + arg_count > self.target {
                let relative_idx = self.target - self.current;
                self.try_mutate_arg(&mut i.sig, relative_idx);
                self.mutated = true;
            }
            self.current += arg_count;
        }
        
        visit_mut::visit_impl_item_fn_mut(self, i);
    }
}

impl Mutator for LifetimeMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = LifetimeCollector {
            count: 0,
            in_trait_impl: false,
        };
        c.visit_file(ast);
        c.count
    }

    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = LifetimeApplier {
            target: index,
            current: 0,
            mutated: false,
            in_trait_impl: false,
        };
        a.visit_file_mut(ast);
        a.mutated
    }
}
