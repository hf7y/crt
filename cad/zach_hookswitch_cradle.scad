difference() {
    union() {
        sphere(r=8);
        cylinder(h=7,r=8);
        translate([0,12,4.3])
import("/home/zach/Downloads/Phone handset hook cradle - 3928257/files/Phone_Handset_Cradle_3.stl");
    }
    union(){
        translate([0,0,6.2/2+8-6.2])
            rotate([0,0,90])
                cube([13.2,6,6.3],center = true);
        translate([0,0,8-6.2-3])
            rotate([0,0,90])
                cube([12.9,4.5,20],center = true);
    }
}