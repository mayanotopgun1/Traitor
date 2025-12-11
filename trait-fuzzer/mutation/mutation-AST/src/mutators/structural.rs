use super::framework::Mutator;
use syn::visit::{self, Visit};
use syn::visit_mut::{self, VisitMut};
use syn::{parse_quote, ItemTrait, TypeParamBound, ItemStruct, ItemImpl, Local, TraitItem, GenericParam};
use syn::WherePredicate;

// =========================================================================
// 1. Type Erasure
// =========================================================================
pub struct TypeErasureMutator;

struct TypeErasureCollector { count: usize }
impl<'ast> Visit<'ast> for TypeErasureCollector {
    fn visit_local(&mut self, local: &'ast Local) {
        if let syn::Pat::Type(_) = &local.pat {
            self.count += 1;
        }
        visit::visit_local(self, local);
    }
}

struct TypeErasureApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for TypeErasureApplier {
    fn visit_local_mut(&mut self, local: &mut Local) {
        if let syn::Pat::Type(pat_type) = &local.pat {
            if self.current == self.target {
                local.pat = *pat_type.pat.clone();
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_local_mut(self, local);
    }
}

impl Mutator for TypeErasureMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = TypeErasureCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = TypeErasureApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 2. Supertrait Expansion
// =========================================================================
pub struct SupertraitExpansionMutator;

struct SupertraitCollector { count: usize }
impl<'ast> Visit<'ast> for SupertraitCollector {
    fn visit_item_trait(&mut self, _: &'ast ItemTrait) {
        self.count += 1;
    }
}

struct SupertraitApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for SupertraitApplier {
    fn visit_item_trait_mut(&mut self, i: &mut ItemTrait) {
        if self.current == self.target {
            let new_bound: TypeParamBound = parse_quote!(Copy);
            i.supertraits.push(new_bound);
            self.mutated = true;
        }
        self.current += 1;
        visit_mut::visit_item_trait_mut(self, i);
    }
}

impl Mutator for SupertraitExpansionMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = SupertraitCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = SupertraitApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 3. Where Clause Expansion
// =========================================================================
pub struct WhereClauseExpansionMutator;

struct WhereClauseCollector { count: usize }
impl<'ast> Visit<'ast> for WhereClauseCollector {
    fn visit_item_struct(&mut self, i: &'ast ItemStruct) {
        if !i.generics.params.is_empty() { self.count += 1; }
        visit::visit_item_struct(self, i);
    }
    fn visit_item_trait(&mut self, i: &'ast ItemTrait) {
        if !i.generics.params.is_empty() { self.count += 1; }
        visit::visit_item_trait(self, i);
    }
    fn visit_item_impl(&mut self, i: &'ast ItemImpl) {
        if !i.generics.params.is_empty() { self.count += 1; }
        visit::visit_item_impl(self, i);
    }
}

struct WhereClauseApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for WhereClauseApplier {
    fn visit_item_struct_mut(&mut self, i: &mut ItemStruct) {
        if !i.generics.params.is_empty() {
            if self.current == self.target {
                let new_predicate: WherePredicate = parse_quote!(T: Copy);
                i.generics.make_where_clause().predicates.push(new_predicate);
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_item_struct_mut(self, i);
    }
    fn visit_item_trait_mut(&mut self, i: &mut ItemTrait) {
        if !i.generics.params.is_empty() {
             if self.current == self.target {
                let new_predicate: WherePredicate = parse_quote!(T: Copy);
                i.generics.make_where_clause().predicates.push(new_predicate);
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_item_trait_mut(self, i);
    }
    fn visit_item_impl_mut(&mut self, i: &mut ItemImpl) {
        if !i.generics.params.is_empty() {
             if self.current == self.target {
                let new_predicate: WherePredicate = parse_quote!(T: Copy);
                i.generics.make_where_clause().predicates.push(new_predicate);
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_item_impl_mut(self, i);
    }
}

impl Mutator for WhereClauseExpansionMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = WhereClauseCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = WhereClauseApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 4. Trait Item Removal
// =========================================================================
pub struct TraitItemRemovalMutator;

struct TraitItemRemovalCollector { count: usize }
impl<'ast> Visit<'ast> for TraitItemRemovalCollector {
    fn visit_item_trait(&mut self, i: &'ast ItemTrait) {
        if !i.items.is_empty() { self.count += 1; }
        visit::visit_item_trait(self, i);
    }
}

struct TraitItemRemovalApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for TraitItemRemovalApplier {
    fn visit_item_trait_mut(&mut self, i: &mut ItemTrait) {
        if !i.items.is_empty() {
            if self.current == self.target {
                i.items.pop();
                self.mutated = true;
            }
            self.current += 1;
        }
        visit_mut::visit_item_trait_mut(self, i);
    }
}

impl Mutator for TraitItemRemovalMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = TraitItemRemovalCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = TraitItemRemovalApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 5. Add Associated Type
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
            let new_item: TraitItem = parse_quote!(type AssociatedType;);
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
// 6. Type Overwriting
// =========================================================================
pub struct TypeOverwritingMutator;

struct TypeOverwritingCollector { count: usize }
impl<'ast> Visit<'ast> for TypeOverwritingCollector {
    fn visit_type(&mut self, i: &'ast syn::Type) {
         if let syn::Type::Path(type_path) = i {
            if let Some(ident) = type_path.path.get_ident() {
                let name = ident.to_string();
                if matches!(name.as_str(), "u32" | "i32" | "String") {
                    self.count += 1;
                }
            }
         }
         visit::visit_type(self, i);
    }
}

struct TypeOverwritingApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for TypeOverwritingApplier {
    fn visit_type_mut(&mut self, i: &mut syn::Type) {
        if let syn::Type::Path(type_path) = i {
            if let Some(ident) = type_path.path.get_ident() {
                let name = ident.to_string();
                if matches!(name.as_str(), "u32" | "i32" | "String") {
                    if self.current == self.target {
                        if name == "u32" { *i = parse_quote!(i32); }
                        else if name == "i32" { *i = parse_quote!(u32); }
                        else if name == "String" { *i = parse_quote!(&str); }
                        self.mutated = true;
                    }
                    self.current += 1;
                }
            }
        }
        visit_mut::visit_type_mut(self, i);
    }
}

impl Mutator for TypeOverwritingMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = TypeOverwritingCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = TypeOverwritingApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 7. Generic Narrowing
// =========================================================================
pub struct GenericNarrowingMutator;

struct GenericNarrowingCollector { count: usize }
impl<'ast> Visit<'ast> for GenericNarrowingCollector {
    fn visit_type(&mut self, i: &'ast syn::Type) {
        if let syn::Type::Path(type_path) = i {
            if let Some(ident) = type_path.path.get_ident() {
                let name = ident.to_string();
                if name.len() == 1 && name.chars().next().unwrap().is_uppercase() {
                    self.count += 1;
                }
            }
        }
        visit::visit_type(self, i);
    }
}

struct GenericNarrowingApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for GenericNarrowingApplier {
    fn visit_type_mut(&mut self, i: &mut syn::Type) {
        if let syn::Type::Path(type_path) = i {
            if let Some(ident) = type_path.path.get_ident() {
                let name = ident.to_string();
                if name.len() == 1 && name.chars().next().unwrap().is_uppercase() {
                    if self.current == self.target {
                        *i = parse_quote!(i32);
                        self.mutated = true;
                    }
                    self.current += 1;
                }
            }
        }
        visit_mut::visit_type_mut(self, i);
    }
}

impl Mutator for GenericNarrowingMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = GenericNarrowingCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = GenericNarrowingApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}

// =========================================================================
// 8. Add Trait
// =========================================================================
pub struct AddTraitMutator;
// For AddTrait, collection is simple: we always have 1 valid mutation point (the file root)
impl Mutator for AddTraitMutator {
    fn collect(&mut self, _ast: &syn::File) -> usize {
        1
    }
    fn mutate(&mut self, ast: &mut syn::File, _index: usize) -> bool {
        let new_trait: ItemTrait = parse_quote!(
            trait NewTrait {
                fn new_method(&self);
            }
        );
        ast.items.push(syn::Item::Trait(new_trait));
        true
    }
}

// =========================================================================
// 9. Add Generic Type
// =========================================================================
pub struct AddGenericTypeMutator;

struct AddGenericTypeCollector { count: usize }
impl<'ast> Visit<'ast> for AddGenericTypeCollector {
    fn visit_generics(&mut self, i: &'ast syn::Generics) {
         // Naive check: does it NOT have NewGen?
         if !i.params.iter().any(|p| if let GenericParam::Type(t) = p { t.ident == "NewGen" } else { false }) {
            self.count += 1;
         }
         visit::visit_generics(self, i);
    }
}

struct AddGenericTypeApplier { target: usize, current: usize, mutated: bool }
impl VisitMut for AddGenericTypeApplier {
    fn visit_generics_mut(&mut self, i: &mut syn::Generics) {
        if !i.params.iter().any(|p| if let GenericParam::Type(t) = p { t.ident == "NewGen" } else { false }) {
             if self.current == self.target {
                if i.lt_token.is_none() {
                    i.lt_token = Some(syn::token::Lt::default());
                    i.gt_token = Some(syn::token::Gt::default());
                }
                let new_param: syn::GenericParam = parse_quote!(NewGen);
                i.params.push(new_param);
                self.mutated = true;
             }
             self.current += 1;
        }
        visit_mut::visit_generics_mut(self, i);
    }
}

impl Mutator for AddGenericTypeMutator {
    fn collect(&mut self, ast: &syn::File) -> usize {
        let mut c = AddGenericTypeCollector { count: 0 };
        c.visit_file(ast);
        c.count
    }
    fn mutate(&mut self, ast: &mut syn::File, index: usize) -> bool {
        let mut a = AddGenericTypeApplier { target: index, current: 0, mutated: false };
        a.visit_file_mut(ast);
        a.mutated
    }
}
