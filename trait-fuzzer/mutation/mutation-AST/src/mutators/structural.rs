use super::framework::Mutator;
use quote::ToTokens;
use rand::Rng;
use syn::visit::{self, Visit};
use syn::visit_mut::{self, VisitMut};
use rand::seq::SliceRandom;
use syn::{parse_quote, GenericParam, Ident, ItemImpl, ItemTrait, TraitItem, TraitItemFn, TraitItemType, Type, TypeParamBound};
use syn::WherePredicate;
use crate::ttdn::{ImplAssocBinding, TtdnInfo};

// =========================================================================
// 0. TTDN
// =========================================================================
// NOTE: TtdnInfo/ImplAssocBinding moved to crate::ttdn (single source of truth).

// =========================================================================
// 1. Add Associated Type
// =========================================================================
pub struct AddAssocTypeMutator;

struct AddAssocTypeCollector { count: usize }
impl<'ast> Visit<'ast> for AddAssocTypeCollector {
    fn visit_item_trait(&mut self, _: &'ast ItemTrait) {
        self.count += 1;
    }
}

struct AddAssocTypeApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for AddAssocTypeApplier {
    fn visit_item_trait_mut(&mut self, i: &mut ItemTrait) {
        if self.current == self.target {
            let mut used: std::collections::HashSet<String> = std::collections::HashSet::new();
            for it in &i.items {
                if let TraitItem::Type(t) = it {
                    used.insert(t.ident.to_string());
                }
            }

            let mut picked: Option<Ident> = None;
            for n in 0..256 {
                let candidate = if n == 0 {
                    "Assoc".to_string()
                } else {
                    format!("Assoc{}", n)
                };

                if !used.contains(&candidate) {
                    picked = Some(syn::Ident::new(&candidate, proc_macro2::Span::call_site()));
                    break;
                }
            }

            let Some(assoc_ident) = picked else {
                self.current += 1;
                visit_mut::visit_item_trait_mut(self, i);
                return;
            };

            // Use a default to avoid breaking existing impls of this trait.
            let rhs_ty: Type = parse_quote!(i32);
            let new_item: TraitItem = parse_quote!(type #assoc_ident = #rhs_ty;);
            i.items.push(new_item);
            self.mutated = true;
        }
        self.current += 1;
        visit_mut::visit_item_trait_mut(self, i);
    }
}

impl Mutator for AddAssocTypeMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = AddAssocTypeCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = AddAssocTypeApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 2. Add Trait
// =========================================================================
pub struct AddTraitMutator;
// For AddTrait, collection is simple: we always have 1 valid mutation point (the file root)
impl Mutator for AddTraitMutator {
    fn collect(&mut self, _ast: &syn::File) -> usize {
        1
    }
    fn mutate(&mut self, ast: &mut syn::File, _index: usize) -> bool {
        let ttdn = TtdnInfo::from_file(&*ast);

        let mut used: std::collections::HashSet<String> = std::collections::HashSet::new();
        for t in &ttdn.traits {
            used.insert(t.to_string());
        }
        for t in &ttdn.types {
            used.insert(t.to_string());
        }

        let mut picked: Option<Ident> = None;
        for i in 0..256 {
            let candidate = if i == 0 {
                "NewTrait".to_string()
            } else {
                format!("NewTrait{}", i)
            };
            if !used.contains(&candidate) {
                picked = Some(syn::Ident::new(&candidate, proc_macro2::Span::call_site()));
                break;
            }
        }

        let Some(trait_ident) = picked else {
            return false;
        };

        // Keep AddTrait minimal: only introduce new traits.
        // Constraints, associated types and methods are handled by other operators.
        let mut rng = rand::thread_rng();
        let new_trait: ItemTrait = if rng.gen_bool(0.5) {
            // non-generic trait
            parse_quote!(trait #trait_ident {})
        } else {
            // generic trait (type generics only)
            parse_quote!(trait #trait_ident<T> {})
        };
        ast.items.push(syn::Item::Trait(new_trait));
        true
    }
}

// =========================================================================
// 3. Add Impl
// =========================================================================
//
// Inserts a new impl block: `impl Trait for Type { ... }`.
// To keep the mutation more likely to compile, we try to synthesize required
// associated types and functions (using `unimplemented!()` bodies).
pub struct AddImplMutator;

impl AddImplMutator {
    fn only_type_params(generics: &syn::Generics) -> Option<Vec<Ident>> {
        let mut out = Vec::new();
        for p in &generics.params {
            match p {
                GenericParam::Type(tp) => out.push(tp.ident.clone()),
                _ => return None,
            }
        }
        Some(out)
    }

    fn uniquify_ident(base: &Ident, used: &mut std::collections::HashSet<String>) -> Ident {
        let base_s = base.to_string();
        if used.insert(base_s.clone()) {
            return base.clone();
        }

        for i in 0..128 {
            let candidate = format!("{}_{}", base_s, i);
            if used.insert(candidate.clone()) {
                return syn::Ident::new(&candidate, base.span());
            }
        }

        // Extremely unlikely fallback.
        syn::Ident::new("G", proc_macro2::Span::call_site())
    }

    fn trait_has_required_items(tr: &ItemTrait) -> bool {
        tr.items.iter().any(|it| match it {
            TraitItem::Fn(f) => f.default.is_none(),
            TraitItem::Type(t) => t.default.is_none(),
            _ => false,
        })
    }

    fn make_impl_items_for_trait(tr: &ItemTrait, ttdn: &TtdnInfo) -> Vec<syn::ImplItem> {
        let mut out: Vec<syn::ImplItem> = Vec::new();

        for it in &tr.items {
            match it {
                TraitItem::Type(assoc) if assoc.default.is_none() => {
                    let assoc_ident = &assoc.ident;
                    let rhs_ty: Type = ttdn
                        .types
                        .first()
                        .cloned()
                        .map(|id| parse_quote!(#id))
                        .unwrap_or_else(|| parse_quote!(i32));

                    out.push(parse_quote!(type #assoc_ident = #rhs_ty;));
                }
                TraitItem::Fn(TraitItemFn { sig, default, .. }) if default.is_none() => {
                    let sig = sig.clone();
                    out.push(parse_quote!(#sig { unimplemented!() }));
                }
                _ => {}
            }
        }

        out
    }
}

impl Mutator for AddImplMutator {
    fn collect(&mut self, _ast: &syn::File) -> usize {
        1
    }

    fn mutate(&mut self, ast: &mut syn::File, _index: usize) -> bool {
        let ttdn = TtdnInfo::from_file(&*ast);
        if ttdn.traits.is_empty() || ttdn.types.is_empty() {
            return false;
        }

        let mut rng = rand::thread_rng();
        const INSTANTIATE_ARG_PROB: f64 = 0.45;

        // Prefer traits already in the file and types already in the file.
        // Avoid adding an impl that already exists.
        for _ in 0..12 {
            let trait_ident = ttdn.traits.choose(&mut rng).cloned();
            let type_ident = ttdn.types.choose(&mut rng).cloned();
            let (Some(trait_ident), Some(type_ident)) = (trait_ident, type_ident) else {
                return false;
            };

            let already = ttdn
                .impl_edges
                .iter()
                .any(|(ty, tr)| *ty == type_ident && *tr == trait_ident);
            if already {
                continue;
            }

            // Find the trait item to synthesize required members.
            let trait_item: Option<&ItemTrait> = ast.items.iter().find_map(|it| match it {
                syn::Item::Trait(t) if t.ident == trait_ident => Some(t),
                _ => None,
            });

            // Find the type definition (struct/enum) to support generic instantiation.
            let type_generics: Option<syn::Generics> = ast.items.iter().find_map(|it| match it {
                syn::Item::Struct(s) if s.ident == type_ident => Some(s.generics.clone()),
                syn::Item::Enum(e) if e.ident == type_ident => Some(e.generics.clone()),
                _ => None,
            });

            // If we can't find the actual definition, keep it simple and try another.
            let Some(tr_def) = trait_item else {
                continue;
            };
            let Some(ty_def_generics) = type_generics else {
                continue;
            };

            // More aggressive support: allow type generics, but only type params (skip lifetime/const).
            let Some(trait_param_idents) = Self::only_type_params(&tr_def.generics) else {
                continue;
            };
            let Some(type_param_idents) = Self::only_type_params(&ty_def_generics) else {
                continue;
            };

            // Build a single impl generics list and instantiate both sides.
            // More aggressive: sometimes instantiate type args with existing concrete types.
            let mut used: std::collections::HashSet<String> = std::collections::HashSet::new();
            let mut impl_params: Vec<Ident> = Vec::new();
            let mut trait_arg_tys: Vec<Type> = Vec::new();
            let mut type_arg_tys: Vec<Type> = Vec::new();

            for p in trait_param_idents {
                if rng.gen_bool(INSTANTIATE_ARG_PROB) {
                    if let Some(concrete) = ttdn.types.choose(&mut rng) {
                        let concrete_ident = concrete.clone();
                        let ty: Type = parse_quote!(#concrete_ident);
                        trait_arg_tys.push(ty);
                        continue;
                    }
                }

                let id = Self::uniquify_ident(&p, &mut used);
                impl_params.push(id.clone());
                let ty: Type = parse_quote!(#id);
                trait_arg_tys.push(ty);
            }
            for p in type_param_idents {
                if rng.gen_bool(INSTANTIATE_ARG_PROB) {
                    if let Some(concrete) = ttdn.types.choose(&mut rng) {
                        let concrete_ident = concrete.clone();
                        let ty: Type = parse_quote!(#concrete_ident);
                        type_arg_tys.push(ty);
                        continue;
                    }
                }

                let id = Self::uniquify_ident(&p, &mut used);
                impl_params.push(id.clone());
                let ty: Type = parse_quote!(#id);
                type_arg_tys.push(ty);
            }

            let trait_path: syn::Path = if trait_arg_tys.is_empty() {
                parse_quote!(#trait_ident)
            } else {
                parse_quote!(#trait_ident < #(#trait_arg_tys),* >)
            };

            let self_ty: Type = if type_arg_tys.is_empty() {
                parse_quote!(#type_ident)
            } else {
                parse_quote!(#type_ident < #(#type_arg_tys),* >)
            };

            let mut new_impl: ItemImpl = parse_quote!(impl #trait_path for #self_ty {});

            if !impl_params.is_empty() {
                new_impl.generics.lt_token = Some(syn::token::Lt::default());
                new_impl.generics.gt_token = Some(syn::token::Gt::default());
                for id in impl_params {
                    let gp: syn::GenericParam = parse_quote!(#id);
                    new_impl.generics.params.push(gp);
                }
            }

            if Self::trait_has_required_items(tr_def) {
                new_impl.items = Self::make_impl_items_for_trait(tr_def, &ttdn);
            }

            ast.items.push(syn::Item::Impl(new_impl));
            return true;
        }

        false
    }
}

// =========================================================================
// 4. Constraint Injection (TTDN-guided)
// =========================================================================
//
// Injects a trait constraint into one of the "constraint-capable" sites:
// - where clauses (impl generics)
// - generic type parameter bounds
// - trait supertraits (inheritance bounds)
// - associated type bounds
//
// The injected constraint is guided by a lightweight TTDN extracted from the
// current seed AST: traits/types and (Type implements Trait) edges.
pub struct ConstraintInjectionMutator;

struct ConstraintInjectionCollector {
    count: usize,
}

impl<'ast> Visit<'ast> for ConstraintInjectionCollector {
    fn visit_item_trait(&mut self, i: &'ast ItemTrait) {
        self.count += 1; // supertrait injection point
        visit::visit_item_trait(self, i);
    }

    fn visit_item_impl(&mut self, i: &'ast ItemImpl) {
        self.count += 1; // where injection point
        visit::visit_item_impl(self, i);
    }

    fn visit_generic_param(&mut self, i: &'ast GenericParam) {
        if matches!(i, GenericParam::Type(_)) {
            self.count += 1; // generic bound injection point
        }
        visit::visit_generic_param(self, i);
    }

    fn visit_trait_item_type(&mut self, _: &'ast TraitItemType) {
        self.count += 1; // associated type bound injection point
    }
}

struct ConstraintInjectionApplier {
    target: usize,
    current: usize,
    mutated: bool,
    ttdn: TtdnInfo,
}

impl ConstraintInjectionApplier {
    fn fallback_trait() -> Ident {
        syn::Ident::new("Copy", proc_macro2::Span::call_site())
    }

    fn choose_trait_prefer_custom(&self, excluded: &[Ident]) -> Ident {
        // Prefer traits defined in the current file (TTDN traits), avoid obvious duplicates.
        let mut rng = rand::thread_rng();
        let candidates: Vec<Ident> = self
            .ttdn
            .traits
            .iter()
            .filter(|t| !excluded.iter().any(|e| e == *t))
            .cloned()
            .collect();

        candidates
            .choose(&mut rng)
            .cloned()
            .unwrap_or_else(Self::fallback_trait)
    }

    fn local_type_params(generics: &syn::Generics) -> Vec<Ident> {
        generics
            .params
            .iter()
            .filter_map(|p| match p {
                GenericParam::Type(tp) => Some(tp.ident.clone()),
                _ => None,
            })
            .collect()
    }

    fn normalize_tokens<T: ToTokens>(node: &T) -> String {
        node.to_token_stream().to_string().split_whitespace().collect()
    }

    fn has_where_predicate(generics: &syn::Generics, predicate: &WherePredicate) -> bool {
        let Some(where_clause) = &generics.where_clause else {
            return false;
        };

        let needle = Self::normalize_tokens(predicate);
        where_clause
            .predicates
            .iter()
            .any(|p| Self::normalize_tokens(p) == needle)
    }

    fn choose_where_predicate_for_generics(
        &self,
        generics: &syn::Generics,
        self_ty_ident: Option<&Ident>,
        excluded_traits: &[Ident],
    ) -> Option<WherePredicate> {
        // 1) Prefer binding a local generic parameter (more "realistic" than concrete-type bounds).
        let mut rng = rand::thread_rng();
        let local_params = Self::local_type_params(generics);
        if let Some(tp) = local_params.choose(&mut rng) {
            let trait_ident = self.choose_trait_prefer_custom(excluded_traits);
            return Some(parse_quote!(#tp: #trait_ident));
        }

        // 2) In impl context, prefer constraining the impl self type.
        if let Some(self_ty) = self_ty_ident {
            // Try to re-use an existing edge if it matches this type.
            let matching: Vec<Ident> = self
                .ttdn
                .impl_edges
                .iter()
                .filter(|(ty, _)| ty == self_ty)
                .map(|(_, tr)| tr.clone())
                .collect();

            if let Some(tr) = matching.choose(&mut rng) {
                return Some(parse_quote!(#self_ty: #tr));
            }

            let trait_ident = self.choose_trait_prefer_custom(excluded_traits);
            return Some(parse_quote!(#self_ty: #trait_ident));
        }

        // 3) Otherwise, fall back to any existing (Type implements Trait) edge.
        if let Some((type_ident, trait_ident)) = self.ttdn.any_constraint_pair() {
            return Some(parse_quote!(#type_ident: #trait_ident));
        }

        // 4) Final fallback: concrete type + a (preferably custom) trait.
        let trait_ident = self.choose_trait_prefer_custom(excluded_traits);
        let type_ident = self.ttdn.types.first().cloned()?;
        Some(parse_quote!(#type_ident: #trait_ident))
    }

    fn choose_projection_where_predicate(&self, prefer_self_ty: Option<&Ident>) -> Option<WherePredicate> {
        // We only inject projection constraints when the seed already provides a concrete binding:
        //   impl Trait for Type { type Assoc = SomeType; }
        // This matches the idea: TTDN guides us to "real" projections.
        const PROJECTION_EQ_PROB: f64 = 0.30;

        let mut rng = rand::thread_rng();
        // 1) Prefer concrete assoc bindings from impl blocks.
        let candidates: Vec<&ImplAssocBinding> = match prefer_self_ty {
            Some(self_ty) => self
                .ttdn
                .impl_assoc_bindings
                .iter()
                .filter(|b| &b.self_ty == self_ty)
                .collect(),
            None => Vec::new(),
        };

        let pool: Vec<&ImplAssocBinding> = if !candidates.is_empty() {
            candidates
        } else {
            self.ttdn.impl_assoc_bindings.iter().collect()
        };

        if let Some(binding) = pool.choose(&mut rng).copied() {
            if rng.gen_bool(PROJECTION_EQ_PROB) {
                let self_ty = &binding.self_ty;
                let tr = &binding.trait_ident;
                let assoc = &binding.assoc_ident;
                let rhs = &binding.rhs_ty;
                return Some(parse_quote!(<#self_ty as #tr>::#assoc = #rhs));
            }

            let bound_trait = self.choose_trait_prefer_custom(&[]);
            let self_ty = &binding.self_ty;
            let tr = &binding.trait_ident;
            let assoc = &binding.assoc_ident;
            return Some(parse_quote!(<#self_ty as #tr>::#assoc: #bound_trait));
        }

        // 2) If there is no concrete binding, still allow a projection *bound* guided by:
        //    - trait-associated-type declarations
        //    - an existing (Type implements Trait) edge
        // This keeps the mutation useful even when assoc types are only defaulted.
        let (tr, assoc) = self.ttdn.trait_assoc_types.choose(&mut rng).cloned()?;
        let impl_types_for_trait: Vec<Ident> = self
            .ttdn
            .impl_edges
            .iter()
            .filter(|(_, tr2)| *tr2 == tr)
            .map(|(ty, _)| ty.clone())
            .collect();

        let self_ty = impl_types_for_trait.choose(&mut rng)?.clone();
        let bound_trait = self.choose_trait_prefer_custom(&[tr.clone()]);
        Some(parse_quote!(<#self_ty as #tr>::#assoc: #bound_trait))
    }

    fn choose_impl_where_predicate(&self, i: &ItemImpl) -> Option<WherePredicate> {
        // In real-world Rust, impl where-clauses mostly constrain local generic params and/or Self.
        // But predicates about other in-scope concrete types also exist (less common). We'll inject
        // those occasionally to increase diversity.
        const PROJECTION_PRED_PROB: f64 = 0.35;
        const UNRELATED_IMPL_EDGE_PROB: f64 = 0.25;

        let mut rng = rand::thread_rng();

        let self_ty_ident = match &*i.self_ty {
            Type::Path(tp) => tp.path.get_ident(),
            _ => None,
        };

        // 0) Occasionally inject a projection constraint to exercise normalization:
        //    where <Type as Trait>::Assoc: Bound
        //    where <Type as Trait>::Assoc = Ty
        if rng.gen_bool(PROJECTION_PRED_PROB) {
            if let Some(pred) = self.choose_projection_where_predicate(self_ty_ident) {
                return Some(pred);
            }
        }

        // 1) Prefer binding a local generic parameter.
        let local_params = Self::local_type_params(&i.generics);
        if let Some(tp) = local_params.choose(&mut rng) {
            let trait_ident = self.choose_trait_prefer_custom(&[]);
            return Some(parse_quote!(#tp: #trait_ident));
        }

        // 2) Occasionally inject an "unrelated" predicate: OtherType: OtherTrait (from TTDN impl edges).
        if rng.gen_bool(UNRELATED_IMPL_EDGE_PROB) {
            let unrelated_edges: Vec<(Ident, Ident)> = self
                .ttdn
                .impl_edges
                .iter()
                .filter(|(ty, _)| self_ty_ident.map(|s| s != ty).unwrap_or(true))
                .cloned()
                .collect();

            if let Some((ty, tr)) = unrelated_edges.choose(&mut rng) {
                return Some(parse_quote!(#ty: #tr));
            }
        }

        // 3) Otherwise, constrain Self if possible (usually the most meaningful).
        self.choose_where_predicate_for_generics(&i.generics, self_ty_ident, &[])
    }

    fn has_bound(bounds: &syn::punctuated::Punctuated<TypeParamBound, syn::token::Plus>, trait_ident: &Ident) -> bool {
        bounds.iter().any(|b| match b {
            TypeParamBound::Trait(tb) => tb.path.get_ident().is_some_and(|id| id == trait_ident),
            _ => false,
        })
    }

    fn has_supertrait(i: &ItemTrait, trait_ident: &Ident) -> bool {
        i.supertraits.iter().any(|b| match b {
            TypeParamBound::Trait(tb) => tb.path.get_ident().is_some_and(|id| id == trait_ident),
            _ => false,
        })
    }
}

impl VisitMut for ConstraintInjectionApplier {
    fn visit_item_trait_mut(&mut self, i: &mut ItemTrait) {
        // supertrait (inheritance) site
        if self.current == self.target {
            let trait_ident = self.choose_trait_prefer_custom(&[i.ident.clone()]);
            if !Self::has_supertrait(i, &trait_ident) {
                let new_bound: TypeParamBound = parse_quote!(#trait_ident);
                i.supertraits.push(new_bound);
                self.mutated = true;
            }
        }
        self.current += 1;

        visit_mut::visit_item_trait_mut(self, i);
    }

    fn visit_item_impl_mut(&mut self, i: &mut ItemImpl) {
        if self.current == self.target {
            let pred = {
                let snapshot: &ItemImpl = &*i;
                self.choose_impl_where_predicate(snapshot)
            };

            if let Some(pred) = pred {
                if !Self::has_where_predicate(&i.generics, &pred) {
                    i.generics.make_where_clause().predicates.push(pred);
                    self.mutated = true;
                }
            }
        }
        self.current += 1;
        visit_mut::visit_item_impl_mut(self, i);
    }

    fn visit_generic_param_mut(&mut self, i: &mut GenericParam) {
        if let GenericParam::Type(tp) = i {
            if self.current == self.target {
                let trait_ident = self.choose_trait_prefer_custom(&[]);
                if !Self::has_bound(&tp.bounds, &trait_ident) {
                    let new_bound: TypeParamBound = parse_quote!(#trait_ident);
                    tp.bounds.push(new_bound);
                    self.mutated = true;
                }
            }
            self.current += 1;
        }
        visit_mut::visit_generic_param_mut(self, i);
    }

    fn visit_trait_item_type_mut(&mut self, i: &mut TraitItemType) {
        if self.current == self.target {
            let trait_ident = self.choose_trait_prefer_custom(&[]);
            if !Self::has_bound(&i.bounds, &trait_ident) {
                let new_bound: TypeParamBound = parse_quote!(#trait_ident);
                i.bounds.push(new_bound);
                self.mutated = true;
            }
        }
        self.current += 1;
        visit_mut::visit_trait_item_type_mut(self, i);
    }
}

impl Mutator for ConstraintInjectionMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = ConstraintInjectionCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }

    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let ttdn = TtdnInfo::from_file(&*ast);
        let mut a = ConstraintInjectionApplier {
            target: index,
            current: 0,
            mutated: false,
            ttdn,
        };
        a.visit_file_mut(ast);
        a.mutated
    }
}
