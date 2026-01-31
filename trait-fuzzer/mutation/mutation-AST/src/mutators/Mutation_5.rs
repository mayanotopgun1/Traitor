// =========================================================================
// LIFETIME OUTLIVE MUTATION (MutationⅤ)
// =========================================================================
use super::framework::Mutator;
use syn::visit::{self, Visit};
use syn::visit_mut::{self, VisitMut};
use syn::{parse_quote, GenericParam, Ident, ImplItemFn, ItemFn, Signature, FnArg, Type, TypeReference, Lifetime, LifetimeParam};
use rand::Rng;

pub struct OutliveMutator;

struct OutliveCollector {
    count: usize,
    in_trait_impl: bool,
}

impl<'ast> Visit<'ast> for OutliveCollector {
    fn visit_item_impl(&mut self, i: &'ast syn::ItemImpl) {
        let old_in_trait = self.in_trait_impl;
        if i.trait_.is_some() {
            self.in_trait_impl = true;
        }
        visit::visit_item_impl(self, i);
        self.in_trait_impl = old_in_trait;
    }

    fn visit_item_fn(&mut self, i: &'ast ItemFn) {
        // Top-level functions are always eligible
        self.count += 1;
        visit::visit_item_fn(self, i);
    }

    fn visit_impl_item_fn(&mut self, i: &'ast ImplItemFn) {
        // Only count if not in trait impl (avoid signature mismatch)
        if !self.in_trait_impl {
            self.count += 1;
        }
        visit::visit_impl_item_fn(self, i);
    }
}

struct OutliveApplier {
    target: usize,
    current: usize,
    mutated: bool,
    in_trait_impl: bool,
}

impl OutliveApplier {
    /// Extract all lifetime parameters from a signature
    fn collect_lifetimes(sig: &Signature) -> Vec<Lifetime> {
        let mut lifetimes = Vec::new();
        for param in &sig.generics.params {
            if let GenericParam::Lifetime(lt_param) = param {
                lifetimes.push(lt_param.lifetime.clone());
            }
        }
        lifetimes
    }

    /// Add an outlive constraint to the signature
    /// Handles 3 cases:
    /// 1. ≥2 existing lifetimes: add constraint between two
    /// 2. 1 existing lifetime: introduce new lifetime + add constraint
    /// 3. 0 existing lifetimes: introduce two lifetimes + convert args to refs + add constraint
    fn add_outlive_constraint(&mut self, sig: &mut Signature) {
        let mut rng = rand::thread_rng();
        let existing_lifetimes = Self::collect_lifetimes(sig);

        match existing_lifetimes.len() {
            // Case 1: Multiple existing lifetimes - add outlive constraint between two
            n if n >= 2 => {
                // Pick two distinct lifetimes
                let idx1 = rng.gen_range(0..existing_lifetimes.len());
                let mut idx2 = rng.gen_range(0..existing_lifetimes.len());
                while idx2 == idx1 {
                    idx2 = rng.gen_range(0..existing_lifetimes.len());
                }

                let lt_a = &existing_lifetimes[idx1];
                let lt_b = &existing_lifetimes[idx2];

                // Add 'b: 'a constraint (meaning 'b outlives 'a)
                // Find the lifetime parameter for lt_b and add the bound
                for param in &mut sig.generics.params {
                    if let GenericParam::Lifetime(lt_param) = param {
                        if lt_param.lifetime == *lt_b {
                            // Add bounds: 'b: 'a
                            if !lt_param.bounds.iter().any(|b| b == lt_a) {
                                lt_param.bounds.push(lt_a.clone());
                            }
                            break;
                        }
                    }
                }
            }

            // Case 2: Single existing lifetime - introduce a new one and add constraint
            1 => {
                let existing_lt = &existing_lifetimes[0];
                let new_lt_ident = Self::generate_unique_lifetime_name(sig, "outlive_new");
                let new_lt = Lifetime::new(&format!("'{}", new_lt_ident), proc_macro2::Span::call_site());

                // Add new lifetime parameter with outlive constraint
                let new_param: GenericParam = parse_quote!(#new_lt: #existing_lt);
                sig.generics.params.push(new_param);

                // Find a non-reference argument and convert it to a reference with new lifetime
                for arg in &mut sig.inputs {
                    if let FnArg::Typed(pat_type) = arg {
                        if !matches!(&*pat_type.ty, Type::Reference(_)) {
                            // Wrap in reference with new lifetime
                            let old_ty = *pat_type.ty.clone();
                            let new_ty = Type::Reference(TypeReference {
                                and_token: parse_quote!(&),
                                lifetime: Some(new_lt.clone()),
                                mutability: None,
                                elem: Box::new(old_ty),
                            });
                            *pat_type.ty = new_ty;
                            break;
                        }
                    }
                }
            }

            // Case 3: No existing lifetimes - introduce two and add constraint
            _ => {
                let lt_a_ident = Self::generate_unique_lifetime_name(sig, "outlive_a");
                let lt_b_ident = Self::generate_unique_lifetime_name(sig, "outlive_b");
                let lt_a = Lifetime::new(&format!("'{}", lt_a_ident), proc_macro2::Span::call_site());
                let lt_b = Lifetime::new(&format!("'{}", lt_b_ident), proc_macro2::Span::call_site());

                // Add lifetime parameters: 'a and 'b: 'a
                sig.generics.params.insert(0, parse_quote!(#lt_a));
                sig.generics.params.insert(1, parse_quote!(#lt_b: #lt_a));

                // Convert first two suitable arguments to references
                let mut converted = 0;
                let target_conversions = 2.min(sig.inputs.len());

                for arg in &mut sig.inputs {
                    if converted >= target_conversions {
                        break;
                    }

                    match arg {
                        FnArg::Receiver(r) => {
                            // Convert self to &'lt self if not already a reference
                            if r.reference.is_none() {
                                let lt = if converted == 0 { lt_a.clone() } else { lt_b.clone() };
                                r.reference = Some((parse_quote!(&), Some(lt)));
                                converted += 1;
                            } else if let Some(ref mut ref_info) = r.reference {
                                // Add lifetime to existing reference
                                let lt = if converted == 0 { lt_a.clone() } else { lt_b.clone() };
                                ref_info.1 = Some(lt);
                                converted += 1;
                            }
                        }
                        FnArg::Typed(pat_type) => {
                            match &*pat_type.ty {
                                Type::Reference(tr) => {
                                    // Add lifetime to existing reference
                                    let lt = if converted == 0 { lt_a.clone() } else { lt_b.clone() };
                                    let old_ty = *tr.elem.clone();
                                    let new_ty = Type::Reference(TypeReference {
                                        and_token: parse_quote!(&),
                                        lifetime: Some(lt),
                                        mutability: tr.mutability,
                                        elem: Box::new(old_ty),
                                    });
                                    *pat_type.ty = new_ty;
                                    converted += 1;
                                }
                                _ => {
                                    // Convert value type to reference
                                    let lt = if converted == 0 { lt_a.clone() } else { lt_b.clone() };
                                    let old_ty = *pat_type.ty.clone();
                                    let new_ty = Type::Reference(TypeReference {
                                        and_token: parse_quote!(&),
                                        lifetime: Some(lt),
                                        mutability: None,
                                        elem: Box::new(old_ty),
                                    });
                                    *pat_type.ty = new_ty;
                                    converted += 1;
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    /// Generate a unique lifetime name that doesn't conflict with existing ones
    fn generate_unique_lifetime_name(sig: &Signature, base: &str) -> Ident {
        let existing: std::collections::HashSet<String> = sig.generics.params.iter()
            .filter_map(|p| {
                if let GenericParam::Lifetime(lt) = p {
                    Some(lt.lifetime.ident.to_string())
                } else {
                    None
                }
            })
            .collect();

        let mut candidate = base.to_string();
        let mut counter = 0;
        while existing.contains(&candidate) {
            counter += 1;
            candidate = format!("{}_{}", base, counter);
        }
        
        Ident::new(&candidate, proc_macro2::Span::call_site())
    }
}

impl VisitMut for OutliveApplier {
    fn visit_item_impl_mut(&mut self, i: &mut syn::ItemImpl) {
        let old_in_trait = self.in_trait_impl;
        if i.trait_.is_some() {
            self.in_trait_impl = true;
        }
        visit_mut::visit_item_impl_mut(self, i);
        self.in_trait_impl = old_in_trait;
    }

    fn visit_item_fn_mut(&mut self, i: &mut ItemFn) {
        if self.mutated {
            return;
        }

        if self.current == self.target {
            self.add_outlive_constraint(&mut i.sig);
            self.mutated = true;
        }
        self.current += 1;

        visit_mut::visit_item_fn_mut(self, i);
    }

    fn visit_impl_item_fn_mut(&mut self, i: &mut ImplItemFn) {
        if self.mutated {
            return;
        }

        if !self.in_trait_impl {
            if self.current == self.target {
                self.add_outlive_constraint(&mut i.sig);
                self.mutated = true;
            }
            self.current += 1;
        }

        visit_mut::visit_impl_item_fn_mut(self, i);
    }
}

impl Mutator for OutliveMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut collector = OutliveCollector {
            count: 0,
            in_trait_impl: false,
        };
        collector.visit_file(ast);
        collector.count
    }

    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut applier = OutliveApplier {
            target: index,
            current: 0,
            mutated: false,
            in_trait_impl: false,
        };
        applier.visit_file_mut(ast);
        applier.mutated
    }
}
