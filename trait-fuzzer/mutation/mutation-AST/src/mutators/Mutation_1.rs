// =========================================================================
// STRUCTURAL MUTATION:
// =========================================================================
use super::framework::Mutator;
use rand::seq::SliceRandom;
use rand::Rng;
use syn::{parse_quote, GenericParam, Ident, ItemImpl, ItemTrait, TraitItem, Type};
use crate::ttdn::TtdnInfo;
use super::trait_pattern;

// =========================================================================
// 1. Add Trait
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

        // Use built-in trait patterns (basic / assoc type / GAT)
        let pattern = trait_pattern::choose_pattern();
        let new_trait: ItemTrait = trait_pattern::build_trait(&trait_ident, pattern);
        ast.items.push(syn::Item::Trait(new_trait));
        true
    }
}

// =========================================================================
// 2. Add Impl
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
        trait_pattern::make_impl_items_for_trait(tr, ttdn)
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