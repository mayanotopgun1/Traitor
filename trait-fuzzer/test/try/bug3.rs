#![feature(specialization)]
trait Marker {}
trait SpecializedTrait {
    const CONST_BOOL: bool;
    const CONST_STR: &'static str;
    fn method() -> &'static str;
}
impl<T> SpecializedTrait for T {
    default const CONST_BOOL: bool = false;
    default const CONST_STR: &'static str = "in default impl";
    #[inline(always)]
    default fn method() -> &'static str {
        "in default impl"
    }
}
impl<T: Marker> SpecializedTrait for T
where
    T: SpecializedTrait,
{
    const CONST_BOOL: bool = true;
    const CONST_STR: &'static str = "in specialized impl";
    fn method() -> &'static str {
        "in specialized impl"
    }
}
fn const_bool<T>() -> &'static str {
    if <T as SpecializedTrait>::CONST_BOOL {
        "in specialized impl"
    } else {
        "in default impl"
    }
}
fn const_str<T>() -> &'static str {
    <T as SpecializedTrait>::CONST_STR
}
fn run_method<T>() -> &'static str {
    <T as SpecializedTrait>::method()
}
struct TypeA;
impl Marker for TypeA {}
struct TypeB;
#[inline(never)]
fn exit_if_not_eq(left: &str, right: &str) {
    if left != right {
        std::process::exit(1);
    }
}
pub fn main() {
    exit_if_not_eq("in specialized impl", const_bool::<TypeA>());
}
